"""
Unit tests for POLIS Daily Work Lifecycle - Step 4D: Slack Listener & Cognitive Integration.

Verifies:
1. Pure greeting addressed to POLIS: lifecycle processing occurs and a conversational response is routed.
2. Compound greeting + substantive question: lifecycle processing occurs and the cognitive engine
   receives the substantive question.
3. Original Slack message text remains unchanged (in ActivityEvent, ConversationContext history, and event dict).
4. Public-channel greeting without a mention: lifecycle processing occurs, but no response is generated.
5. Explicit sign-off: lifecycle processing closes the session and addressed conversation receives an acknowledgement.
6. Ordinary farewell: no workday-session closure occurs (session remains active).
7. Existing direct-message, mention, and established-thread routing behavior remains intact.
8. No task ownership is inferred from people mentioned in greeting messages.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from application.activity import (
    ActivityDetector,
    ActivityProcessor,
    ActivityService,
    AttendanceCalculator,
)
from application.cognitive.cognitive_planner import CognitivePlanner
from connectors.slack.routing import clean_slack_text
from connectors.slack.socket.listener import SlackSocketListener
from domain.activity import (
    ActivityEvent,
    ActivityRepository,
    ActivityType,
    InMemoryPersonPreferenceRepository,
    InMemoryWorkdaySessionRepository,
    PersonPreference,
    WorkdaySession,
    WorkdaySessionStatus,
)
from domain.reasoning.value_objects import (
    ConversationContext,
    IntentCategory,
    Question,
)
from engines.slack.dto import SlackMessage as ActivitySlackMessage
from engines.slack.router.slack_intent_router import SlackIntentRouter
from infrastructure.database.conversation_repository import InMemoryConversationRepository


# ==============================================================================
# In-Memory Activity Repository Stub
# ==============================================================================

class FakeActivityRepository(ActivityRepository):
    """In-memory stub ActivityRepository for capturing saved lifecycle events."""

    def __init__(self) -> None:
        self.saved_events: list[ActivityEvent] = []

    def save(self, event: ActivityEvent) -> None:
        self.saved_events.append(event)

    def find_for_person(
        self,
        person_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ActivityEvent]:
        events = [e for e in self.saved_events if e.person_id == person_id]
        if start:
            events = [e for e in events if e.occurred_at >= start]
        if end:
            events = [e for e in events if e.occurred_at <= end]
        return events

    def find_people_by_name(self, person_name: str) -> list[ActivityEvent]:
        return [e for e in self.saved_events if e.person_name == person_name]

    def find_currently_on_break(self) -> list[ActivityEvent]:
        return []

    def find_currently_working(self) -> list[ActivityEvent]:
        return []

    def find_currently_off_work(self) -> list[ActivityEvent]:
        return []

    def find_latest_for_people(self) -> list[ActivityEvent]:
        return []


# ==============================================================================
# Fixtures & Test Harness Setup
# ==============================================================================

@pytest.fixture
def activity_repo() -> FakeActivityRepository:
    return FakeActivityRepository()


@pytest.fixture
def workday_repo() -> InMemoryWorkdaySessionRepository:
    return InMemoryWorkdaySessionRepository()


@pytest.fixture
def preference_repo() -> InMemoryPersonPreferenceRepository:
    return InMemoryPersonPreferenceRepository()


@pytest.fixture
def conv_repo() -> InMemoryConversationRepository:
    return InMemoryConversationRepository()


@pytest.fixture
def activity_service(
    activity_repo: FakeActivityRepository,
    workday_repo: InMemoryWorkdaySessionRepository,
    preference_repo: InMemoryPersonPreferenceRepository,
) -> ActivityService:
    return ActivityService(
        repository=activity_repo,
        attendance_calculator=AttendanceCalculator(),
        workday_session_repository=workday_repo,
        person_preference_repository=preference_repo,
        default_timezone="UTC",
    )


@pytest.fixture
def activity_processor(
    activity_service: ActivityService,
    workday_repo: InMemoryWorkdaySessionRepository,
    preference_repo: InMemoryPersonPreferenceRepository,
) -> ActivityProcessor:
    return ActivityProcessor(
        detector=ActivityDetector(),
        activity_service=activity_service,
        workday_session_repository=workday_repo,
        person_preference_repository=preference_repo,
    )


@pytest.fixture
def mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.ask.return_value = MagicMock(
        text="Hello! How can I help you today?",
        pending_operation=None,
        clear_pending=False,
    )
    return engine


@pytest.fixture
def mock_responder() -> MagicMock:
    responder = MagicMock()
    responder.send_message.return_value = "sent-100"
    responder.reply.return_value = "sent-100"
    return responder


@pytest.fixture
def mock_identity() -> MagicMock:
    identity = MagicMock()
    identity.get_display_name.side_effect = lambda uid: {
        "U_ALICE": "Alice",
        "U_BOB": "Bob",
        "U_BOT": "POLIS",
    }.get(uid, uid)
    identity.get_workspace_users.return_value = [
        {"id": "U_ALICE", "name": "alice", "real_name": "Alice"},
        {"id": "U_BOB", "name": "bob", "real_name": "Bob"},
    ]
    return identity


@pytest.fixture
def intent_router(
    mock_engine: MagicMock,
    mock_responder: MagicMock,
    conv_repo: InMemoryConversationRepository,
    mock_identity: MagicMock,
) -> SlackIntentRouter:
    return SlackIntentRouter(
        engine=mock_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=conv_repo,
        identity_service=mock_identity,
        activity_detector=ActivityDetector(),
    )


@pytest.fixture
def slack_harness(
    activity_processor: ActivityProcessor,
    conv_repo: InMemoryConversationRepository,
    intent_router: SlackIntentRouter,
    mock_responder: MagicMock,
    mock_identity: MagicMock,
    mock_engine: MagicMock,
    workday_repo: InMemoryWorkdaySessionRepository,
    activity_repo: FakeActivityRepository,
    preference_repo: InMemoryPersonPreferenceRepository,
):
    """
    Constructs an offline SlackSocketListener wired to real ActivityProcessor,
    real SlackIntentRouter, and in-memory repositories.
    """
    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler"), \
         patch("connectors.slack.socket.listener.SlackConnector"), \
         patch("connectors.slack.socket.listener.SlackClient"), \
         patch("connectors.slack.socket.listener.SlackResponder", return_value=mock_responder):

        mock_calendar = MagicMock()
        mock_calendar.handle_message.return_value = None
        mock_reminder = MagicMock()

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=MagicMock(),
            activity_processor=activity_processor,
            reminder_service=mock_reminder,
            calendar_agent=mock_calendar,
            conversation_repository=conv_repo,
            intent_router=intent_router,
        )
        listener._responder = mock_responder
        listener._identity_service = mock_identity
        listener._intent_router = intent_router

        mock_settings = MagicMock()
        mock_settings.slack_bot_user_id = "U_BOT"
        mock_settings.reminder_timezone = "UTC"
        mock_settings.reminder_time_1 = "09:00"
        mock_settings.reminder_time_2 = "17:00"

        with patch("connectors.slack.socket.listener.get_settings", return_value=mock_settings):
            handler = listener._app.event.return_value.call_args[0][0]
            yield {
                "listener": listener,
                "handler": handler,
                "workday_repo": workday_repo,
                "activity_repo": activity_repo,
                "preference_repo": preference_repo,
                "conv_repo": conv_repo,
                "engine": mock_engine,
                "responder": mock_responder,
                "settings": mock_settings,
                "router": intent_router,
            }


# ==============================================================================
# Requirement 1: Pure greeting addressed to POLIS
# ==============================================================================

@pytest.mark.asyncio
async def test_pure_greeting_addressed_to_polis_triggers_lifecycle_and_conversational_response(slack_harness):
    """
    1. Pure greeting addressed to POLIS:
       - ActivityProcessor records WORK_START and activates a WorkdaySession.
       - A conversational greeting response is routed via the responder.
       - CognitivePlanner plans pure greetings as GENERAL_CONVERSATION.
    """
    h = slack_harness
    event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning!",
        "ts": "1762128000.100000",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event, MagicMock())

    # 1. Lifecycle processing occurred
    active_session = h["workday_repo"].find_active("U_ALICE")
    assert active_session is not None
    assert active_session.person_name == "Alice"
    assert active_session.status == WorkdaySessionStatus.ACTIVE

    # 2. Activity event saved
    events = h["activity_repo"].find_for_person("U_ALICE")
    assert len(events) == 1
    assert events[0].activity_type == ActivityType.WORK_START

    # 3. Intent router and engine called with pure greeting
    assert h["engine"].ask.called
    asked_question: Question = h["engine"].ask.call_args[0][0]
    assert asked_question.text == "Good morning!"
    assert asked_question.target_user_id is None

    # 4. Conversational response sent
    assert h["responder"].reply.called

    # 5. Verify CognitivePlanner greeting classification
    planner = CognitivePlanner()
    plan = planner.plan(asked_question)
    assert plan.intent == IntentCategory.GENERAL_CONVERSATION


# ==============================================================================
# Requirement 2: Compound greeting + substantive question
# ==============================================================================

@pytest.mark.asyncio
async def test_compound_greeting_and_substantive_question_routes_substantive_query(slack_harness):
    """
    2. Compound greeting + substantive question:
       - ActivityProcessor records workday-start lifecycle event and opens session.
       - Cognitive engine receives the substantive query WITHOUT greeting prefix or bot mention.
       - CognitivePlanner classifies it as substantive organizational inquiry.
    """
    h = slack_harness
    event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning, can you check the project roadmap?",
        "ts": "1762128000.100001",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event, MagicMock())

    # 1. Lifecycle processing occurred
    active_session = h["workday_repo"].find_active("U_ALICE")
    assert active_session is not None
    assert active_session.status == WorkdaySessionStatus.ACTIVE

    # 2. Cognitive engine receives ONLY the substantive question
    assert h["engine"].ask.called
    asked_question: Question = h["engine"].ask.call_args[0][0]
    assert asked_question.text == "can you check the project roadmap?"
    assert "good morning" not in asked_question.text.lower()
    assert "<@u_bot>" not in asked_question.text.lower()

    # 3. Planner classifies as substantive query, not general conversation
    planner = CognitivePlanner()
    plan = planner.plan(asked_question)
    assert plan.intent != IntentCategory.GENERAL_CONVERSATION


# ==============================================================================
# Requirement 3: Original Slack message text remains unchanged
# ==============================================================================

@pytest.mark.asyncio
async def test_original_slack_message_text_preserved(slack_harness):
    """
    3. Original Slack message text remains unchanged:
       - In ActivityEvent note / text.
       - In ConversationContext history recorded in conversation repository.
       - The raw event dict passed to listener is not mutated in place.
    """
    h = slack_harness
    raw_text = "<@U_BOT> Good morning team, can you check the project roadmap?"
    event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": raw_text,
        "ts": "1762128000.100002",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event, MagicMock())

    # Raw event dict text unchanged
    assert event["text"] == raw_text

    # Activity event recorded original text
    events = h["activity_repo"].find_for_person("U_ALICE")
    assert len(events) == 1
    assert events[0].note == raw_text

    # Conversation repository preserved original user message
    ctx = h["conv_repo"].get("D_ALICE", "1762128000.100002")
    assert ctx is not None
    assert len(ctx.history) >= 2
    assert ctx.history[0]["role"] == "user"
    assert ctx.history[0]["content"] == raw_text


# ==============================================================================
# Requirement 4: Public-channel greeting without a mention is silent
# ==============================================================================

@pytest.mark.asyncio
async def test_public_channel_greeting_without_mention_is_silent_lifecycle_only(slack_harness):
    """
    4. Public-channel greeting without a mention:
       - Lifecycle processing occurs and session is activated.
       - No cognitive reply or responder message is generated (remains silent).
    """
    h = slack_harness
    event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "Good morning team!",
        "ts": "1762128000.100003",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event, MagicMock())

    # 1. Lifecycle processing occurred
    active_session = h["workday_repo"].find_active("U_ALICE")
    assert active_session is not None
    assert active_session.status == WorkdaySessionStatus.ACTIVE

    # 2. Activity event saved
    events = h["activity_repo"].find_for_person("U_ALICE")
    assert len(events) == 1

    # 3. No response generated (silent)
    assert not h["engine"].ask.called
    assert not h["responder"].send_message.called
    assert not h["responder"].reply.called


# ==============================================================================
# Requirement 5: Explicit sign-off closes session and receives acknowledgement
# ==============================================================================

@pytest.mark.asyncio
async def test_explicit_signoff_closes_session_and_routes_acknowledgement(slack_harness):
    """
    5. Explicit sign-off:
       - ActivityProcessor closes the workday session (status = COMPLETED).
       - Addressed conversation to POLIS receives conversational acknowledgement.
       - CognitivePlanner plans explicit sign-offs as GENERAL_CONVERSATION.
    """
    h = slack_harness

    # 1. Seed an active workday session for Alice
    start_event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning",
        "ts": "1762128000.100004",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](start_event, MagicMock())

    active_session = h["workday_repo"].find_active("U_ALICE")
    assert active_session is not None

    h["engine"].ask.reset_mock()
    h["responder"].reply.reset_mock()

    # 2. Alice sends explicit sign-off addressed to POLIS
    signoff_event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> I am signing off for today",
        "ts": "1762156800.100005",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](signoff_event, MagicMock())

    # Session closed
    active_after = h["workday_repo"].find_active("U_ALICE")
    assert active_after is None

    closed_session = h["workday_repo"].find_latest_for_person("U_ALICE")
    assert closed_session is not None
    assert closed_session.status == WorkdaySessionStatus.CLOSED

    # Conversational acknowledgement sent
    assert h["engine"].ask.called
    assert h["responder"].reply.called

    # Verify CognitivePlanner classifies explicit sign-off as GENERAL_CONVERSATION
    planner = CognitivePlanner()
    plan = planner.plan(Question("I am signing off for today"))
    assert plan.intent == IntentCategory.GENERAL_CONVERSATION


# ==============================================================================
# Requirement 6: Ordinary farewell does not close workday session
# ==============================================================================

@pytest.mark.asyncio
async def test_ordinary_farewell_does_not_close_workday_session(slack_harness):
    """
    6. Ordinary farewells:
       - Farewells like 'bye' or 'see you tomorrow' remain conversational.
       - They NEVER close the workday session.
       - When addressed to POLIS, they receive a normal conversational response.
    """
    h = slack_harness

    # 1. Seed an active session
    start_event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning",
        "ts": "1762128000.100006",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](start_event, MagicMock())

    active_session = h["workday_repo"].find_active("U_ALICE")
    assert active_session is not None

    h["engine"].ask.reset_mock()
    h["responder"].reply.reset_mock()

    # 2. Alice sends ordinary farewell
    farewell_event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> See you tomorrow!",
        "ts": "1762156800.100007",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](farewell_event, MagicMock())

    # Session remains active (NOT closed)
    active_after = h["workday_repo"].find_active("U_ALICE")
    assert active_after is not None
    assert active_after.identifier.graph_id == active_session.identifier.graph_id
    assert active_after.status == WorkdaySessionStatus.ACTIVE

    # Conversational response routed
    assert h["engine"].ask.called
    assert h["responder"].reply.called

    # Verify CognitivePlanner classifies ordinary farewell as GENERAL_CONVERSATION
    planner = CognitivePlanner()
    plan = planner.plan(Question("See you tomorrow!"))
    assert plan.intent == IntentCategory.GENERAL_CONVERSATION


# ==============================================================================
# Requirement 7: Existing DM, mention, and established-thread routing intact
# ==============================================================================

@pytest.mark.asyncio
async def test_existing_routing_behavior_dm_mention_established_thread_intact(slack_harness):
    """
    7. Existing routing behavior remains intact:
       - Direct messages without mention are answered.
       - Channel messages with mention are answered.
       - Established thread follow-ups without mention are answered.
       - Unrelated thread follow-ups and unmentioned channel messages are ignored.
    """
    h = slack_harness

    # Case A: DM without mention
    dm_event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "What is our company holiday policy?",
        "ts": "1762128000.100008",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](dm_event, MagicMock())
    assert h["engine"].ask.called
    h["engine"].ask.reset_mock()

    # Case B: Channel message with mention
    channel_mention_event = {
        "user": "U_BOB",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Where are the Q3 design docs?",
        "ts": "1762128000.100009",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](channel_mention_event, MagicMock())
    assert h["engine"].ask.called
    h["engine"].ask.reset_mock()

    # Case C: Established thread follow-up without mention
    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_GENERAL", thread_ts="1762128000.100010")
    ctx = ctx.add_exchange("Initial inquiry", "Initial reply")
    h["conv_repo"].save(ctx)

    thread_followup_event = {
        "user": "U_BOB",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "Can you summarize that further?",
        "ts": "1762128000.100011",
        "thread_ts": "1762128000.100010",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](thread_followup_event, MagicMock())
    assert h["engine"].ask.called
    h["engine"].ask.reset_mock()

    # Case D: Unrelated channel message without mention is ignored
    unrelated_event = {
        "user": "U_BOB",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "Hey everyone, grab a donut in the breakroom",
        "ts": "1762128000.100012",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](unrelated_event, MagicMock())
    assert not h["engine"].ask.called


# ==============================================================================
# Requirement 8: No task ownership inferred from people mentioned in greeting
# ==============================================================================

@pytest.mark.asyncio
async def test_no_task_ownership_inferred_from_people_mentioned_in_greeting(slack_harness):
    """
    8. No task ownership is inferred from people mentioned in greeting messages:
       - Compound greeting mentioning a colleague:
         'Good morning Bob, can you check the roadmap?'
         -> target_user_id must be None, NOT 'U_BOB'.
       - Pure greeting mentioning a colleague:
         'Good morning Bob!'
         -> target_user_id must be None.
       - Genuinely targeted substantive inquiry:
         'Can you check Bob's tasks?'
         -> target_user_id IS 'U_BOB'.
    """
    h = slack_harness

    # Subcase A: Compound greeting with colleague name
    event_compound = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning Bob, can you check the roadmap?",
        "ts": "1762128000.100013",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event_compound, MagicMock())

    assert h["engine"].ask.called
    asked_question: Question = h["engine"].ask.call_args[0][0]
    assert asked_question.text == "can you check the roadmap?"
    # Crucial check: target_user_id must NOT be resolved to Bob
    assert asked_question.target_user_id is None
    h["engine"].ask.reset_mock()

    # Subcase B: Pure greeting with colleague name
    event_pure = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning Bob!",
        "ts": "1762128000.100014",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event_pure, MagicMock())

    assert h["engine"].ask.called
    asked_pure: Question = h["engine"].ask.call_args[0][0]
    # Pure greeting must have target_user_id as None
    assert asked_pure.target_user_id is None
    h["engine"].ask.reset_mock()

    # Subcase C: Legitimate task query mentioning Bob
    event_legit = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Can you check Bob's tasks?",
        "ts": "1762128000.100015",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event_legit, MagicMock())

    assert h["engine"].ask.called
    asked_legit: Question = h["engine"].ask.call_args[0][0]
    assert asked_legit.target_user_id == "U_BOB"


# ==============================================================================
# Validation Scenario 2: Repeated greeting does not create duplicate
# ==============================================================================

@pytest.mark.asyncio
async def test_repeated_greeting_does_not_create_duplicate_or_overwrite_started_at(slack_harness):
    """
    Validation Scenario 2:
    A user's repeated greeting does not create another active session or overwrite
    the original start timestamp.
    """
    h = slack_harness

    # First greeting at 09:00:00 UTC
    event_1 = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning!",
        "ts": "1762128000.100000",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event_1, MagicMock())

    active_session_1 = h["workday_repo"].find_active("U_ALICE")
    assert active_session_1 is not None
    orig_started_at = active_session_1.started_at
    orig_id = active_session_1.identifier.graph_id

    h["engine"].ask.reset_mock()
    h["responder"].reply.reset_mock()

    # Second greeting at 10:00:00 UTC
    event_2 = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Hi POLIS",
        "ts": "1762131600.100000",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event_2, MagicMock())

    # Active session is unchanged
    active_session_2 = h["workday_repo"].find_active("U_ALICE")
    assert active_session_2 is not None
    assert active_session_2.identifier.graph_id == orig_id
    assert active_session_2.started_at == orig_started_at

    # Conversational greeting response still routed
    assert h["engine"].ask.called
    assert h["responder"].reply.called


# ==============================================================================
# Validation Scenario 4: Explicit work start creates session when none active
# ==============================================================================

@pytest.mark.asyncio
async def test_explicit_work_start_creates_session_when_none_active(slack_harness):
    """
    Validation Scenario 4:
    An explicit work-start phrase creates a session when none is active.
    """
    h = slack_harness

    event = {
        "user": "U_BOB",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Starting work",
        "ts": "1762128000.100016",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event, MagicMock())

    active_session = h["workday_repo"].find_active("U_BOB")
    assert active_session is not None
    assert active_session.person_name == "Bob"
    assert active_session.status == WorkdaySessionStatus.ACTIVE

    events = h["activity_repo"].find_for_person("U_BOB")
    assert len(events) == 1
    assert events[0].activity_type == ActivityType.WORK_START
    assert h["responder"].reply.called


# ==============================================================================
# Validation Scenario 6: Repeated sign-off idempotent
# ==============================================================================

@pytest.mark.asyncio
async def test_repeated_signoff_idempotent_no_additional_changes(slack_harness):
    """
    Validation Scenario 6:
    Reprocessing the same or a repeated sign-off does not create additional changes or crash.
    """
    h = slack_harness

    # 1. Start active session
    start_event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning",
        "ts": "1762128000.100017",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](start_event, MagicMock())

    active = h["workday_repo"].find_active("U_ALICE")
    assert active is not None

    # 2. First sign-off at 17:00:00 UTC
    signoff_1 = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> I am signing off for today",
        "ts": "1762156800.100018",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](signoff_1, MagicMock())

    closed_session = h["workday_repo"].find_latest_for_person("U_ALICE")
    assert closed_session is not None
    assert closed_session.status == WorkdaySessionStatus.CLOSED
    orig_ended_at = closed_session.ended_at

    h["engine"].ask.reset_mock()
    h["responder"].reply.reset_mock()

    # 3. Repeated sign-off at 17:05:00 UTC
    signoff_2 = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> signing off for today",
        "ts": "1762157100.100019",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](signoff_2, MagicMock())

    # Session remains closed, ended_at unchanged
    after_session = h["workday_repo"].find_latest_for_person("U_ALICE")
    assert after_session is not None
    assert after_session.status == WorkdaySessionStatus.CLOSED
    assert after_session.ended_at == orig_ended_at

    # Acknowledgement still routed to user
    assert h["engine"].ask.called
    assert h["responder"].reply.called


# ==============================================================================
# Validation Scenario 8: Split shifts on same work date
# ==============================================================================

@pytest.mark.asyncio
async def test_split_shift_creates_distinct_session_on_same_local_work_date(slack_harness):
    """
    Validation Scenario 8:
    A new work-start after closure creates a distinct session on the same local work date.
    """
    h = slack_harness

    # Shift 1 start at 09:00 UTC
    shift1_start = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning",
        "ts": "1762128000.100020",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](shift1_start, MagicMock())

    session_1 = h["workday_repo"].find_active("U_ALICE")
    assert session_1 is not None
    work_date = session_1.work_date

    # Shift 1 end at 13:00 UTC
    shift1_end = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> signing off for today",
        "ts": "1762142400.100021",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](shift1_end, MagicMock())

    assert h["workday_repo"].find_active("U_ALICE") is None

    # Shift 2 start at 15:00 UTC (same day)
    shift2_start = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good afternoon",
        "ts": "1762149600.100022",
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](shift2_start, MagicMock())

    session_2 = h["workday_repo"].find_active("U_ALICE")
    assert session_2 is not None
    assert session_2.status == WorkdaySessionStatus.ACTIVE
    assert session_2.work_date == work_date
    assert session_2.identifier.graph_id != session_1.identifier.graph_id

    # Verify repository has 2 sessions for Alice on this work_date
    day_sessions = h["workday_repo"].find_for_person_on_date("U_ALICE", work_date)
    assert len(day_sessions) == 2
    assert {s.status for s in day_sessions} == {WorkdaySessionStatus.CLOSED, WorkdaySessionStatus.ACTIVE}


# ==============================================================================
# Validation Scenario 9: Timezone boundary derivation
# ==============================================================================

@pytest.mark.asyncio
async def test_utc_timestamp_derives_correct_local_work_date_across_timezone_boundary(slack_harness):
    """
    Validation Scenario 9:
    UTC timestamps correctly produce the expected local work date according to user timezone.
    For example: 2026-11-03 21:00:00 UTC is 2026-11-04 02:30:00 in Asia/Kolkata (+5:30).
    """
    h = slack_harness

    # Save user preference for Asia/Kolkata
    pref = PersonPreference.create(
        person_id="U_BOB",
        preferred_timezone="Asia/Kolkata",
    )
    h["preference_repo"].save(pref)

    # 2026-11-03 21:00:00 UTC
    utc_dt = datetime(2026, 11, 3, 21, 0, 0, tzinfo=timezone.utc)
    ts_str = f"{utc_dt.timestamp():.6f}"

    event = {
        "user": "U_BOB",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> Good morning",
        "ts": ts_str,
    }
    with patch("connectors.slack.socket.listener.get_settings", return_value=h["settings"]):
        await h["handler"](event, MagicMock())

    session = h["workday_repo"].find_active("U_BOB")
    assert session is not None
    assert session.timezone == "Asia/Kolkata"
    # In Asia/Kolkata, 21:00 UTC on Nov 3 is 02:30 on Nov 4
    assert session.work_date == date(2026, 11, 4)
