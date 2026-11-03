"""
Comprehensive automated unit tests for POLIS Daily Work Lifecycle — Step 6:
Personalized Morning Greeting & Task Briefing.

Covers all 14 required behavioral scenarios:
1. Greeting by a known user returns a personalized greeting using their display name.
2. Greeting retrieves all open tasks assigned to that Slack user.
3. In-progress tasks are included.
4. Completed tasks are excluded.
5. Tasks assigned to other people are excluded.
6. Overdue and due-soon tasks are highlighted only when supported by actual dates.
7. No-task greeting returns a friendly response without fabricated tasks.
8. Task retrieval failure does not produce a misleading empty-task response.
9. Greeting with a substantive question still answers the question normally.
10. Ordinary farewell does not trigger a morning briefing.
11. Public-channel greeting without a mention does not disclose task details.
12. Task selection leads to useful next-step guidance without unauthorized task status changes.
13. Missing display name uses a safe fallback.
14. Duplicate greetings do not duplicate tasks or create new workday sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from application.activity import ActivityDetector, ActivityProcessor, ActivityService, AttendanceCalculator
from application.cognitive import CognitivePlanner, SimpleCognitiveEngine
from domain.activity import ActivityEvent, ActivityType, WorkdaySessionStatus
from domain.activity.repositories import (
    InMemoryPersonPreferenceRepository,
    InMemoryWorkdaySessionRepository,
)
from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.operations.repositories.in_memory_operational_item_repository import (
    InMemoryOperationalItemRepository,
)
from domain.reasoning import Answer, ConversationContext, Question
from engines.slack.dto import SlackMessage
from engines.slack.router import SlackIntentRouter
from infrastructure.database.conversation_repository import InMemoryConversationRepository


# ==============================================================================
# Helper Factories & Fakes
# ==============================================================================

def make_task(
    *,
    summary: str,
    owner_id: str,
    owner_name: str = "",
    status: OperationalItemStatus = OperationalItemStatus.OPEN,
    priority: OperationalItemPriority = OperationalItemPriority.MEDIUM,
    due_at: datetime | None = None,
    business_id: str = "",
) -> OperationalItem:
    return OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary=summary,
        owner_id=owner_id,
        owner_name=owner_name,
        status=status,
        priority=priority,
        due_at=due_at,
        business_id=business_id or f"task_{summary[:10].strip().replace(' ', '_')}",
    )


class FakeActivityRepository:
    def __init__(self) -> None:
        self.saved_events: list[ActivityEvent] = []

    def save(self, event: ActivityEvent) -> ActivityEvent:
        self.saved_events.append(event)
        return event

    def find_for_person(self, person_id: str) -> list[ActivityEvent]:
        return [e for e in self.saved_events if e.person_id == person_id]

    def find_latest_for_person(self, person_id: str) -> ActivityEvent | None:
        matching = [e for e in self.saved_events if e.person_id == person_id]
        return matching[-1] if matching else None

    def find_between(self, start: datetime, end: datetime) -> list[ActivityEvent]:
        return [e for e in self.saved_events if start <= e.timestamp <= end]

    def find_for_person_by_name(self, person_name: str) -> list[ActivityEvent]:
        return [e for e in self.saved_events if e.person_name == person_name]


class MockIdentityDirectory:
    def __init__(self, directory: dict[str, str] | None = None) -> None:
        self._dir = directory or {
            "U_ALICE": "Alice",
            "U_BOB": "Bob",
            "U_AKSHAT": "Akshat",
            "U_BOT": "POLIS",
        }

    def get_display_name(self, user_id: str) -> str:
        return self._dir.get(user_id, user_id)

    def get_workspace_users(self) -> list[dict]:
        return [
            {
                "id": uid,
                "name": name.lower(),
                "real_name": name,
                "profile": {"display_name": name},
            }
            for uid, name in self._dir.items()
        ]


# ==============================================================================
# Pytest Fixtures
# ==============================================================================

@pytest.fixture
def op_repo() -> InMemoryOperationalItemRepository:
    return InMemoryOperationalItemRepository()


@pytest.fixture
def identity_service() -> MockIdentityDirectory:
    return MockIdentityDirectory()


@pytest.fixture
def workday_repo() -> InMemoryWorkdaySessionRepository:
    return InMemoryWorkdaySessionRepository()


@pytest.fixture
def preference_repo() -> InMemoryPersonPreferenceRepository:
    return InMemoryPersonPreferenceRepository()


@pytest.fixture
def activity_repo() -> FakeActivityRepository:
    return FakeActivityRepository()


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
def mock_qa() -> MagicMock:
    qa = MagicMock()
    qa.answer.return_value = Answer(
        text="Hello! How can I help you today?",
        is_conversational=True,
    )
    return qa


@pytest.fixture
def cognitive_engine(
    op_repo: InMemoryOperationalItemRepository,
    mock_qa: MagicMock,
    identity_service: MockIdentityDirectory,
) -> SimpleCognitiveEngine:
    planner = CognitivePlanner()
    return SimpleCognitiveEngine(
        pipeline=MagicMock(),
        question_answering=mock_qa,
        planner=planner,
        operational_item_repository=op_repo,
        identity_resolver=identity_service,
    )


@pytest.fixture
def mock_responder() -> MagicMock:
    resp = MagicMock()
    resp.reply.return_value = "sent-ts-123"
    return resp


@pytest.fixture
def intent_router(
    cognitive_engine: SimpleCognitiveEngine,
    mock_responder: MagicMock,
    identity_service: MockIdentityDirectory,
) -> SlackIntentRouter:
    return SlackIntentRouter(
        engine=cognitive_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=InMemoryConversationRepository(),
        identity_service=identity_service,
        activity_detector=ActivityDetector(),
    )


# ==============================================================================
# Scenario 1: Greeting by a known user uses display name
# ==============================================================================

def test_greeting_known_user_uses_display_name(cognitive_engine: SimpleCognitiveEngine, op_repo: InMemoryOperationalItemRepository):
    """
    1. Greeting by a known user returns a personalized greeting using their display name.
    """
    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    assert answer.text.startswith("Good morning, Alice! 👋")
    assert "U_ALICE" not in answer.text.split("\n")[0]


# ==============================================================================
# Scenario 2: Greeting retrieves all open tasks assigned to that Slack user
# ==============================================================================

def test_greeting_retrieves_open_tasks_assigned_to_user(cognitive_engine: SimpleCognitiveEngine, op_repo: InMemoryOperationalItemRepository):
    """
    2. Greeting retrieves all open tasks assigned to that Slack user.
    """
    due_date = datetime.now(timezone.utc) + timedelta(days=5)
    t1 = make_task(summary="Finalize Q4 roadmap", owner_id="U_ALICE", owner_name="Alice", status=OperationalItemStatus.OPEN, due_at=due_date)
    t2 = make_task(summary="Prepare sprint retrospective", owner_id="U_ALICE", owner_name="Alice", status=OperationalItemStatus.OPEN)
    op_repo.save(t1)
    op_repo.save(t2)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    assert "You currently have 2 open tasks:" in answer.text
    assert "Finalize Q4 roadmap — Open" in answer.text
    assert "Prepare sprint retrospective — Open" in answer.text
    assert due_date.strftime("%Y-%m-%d") in answer.text


# ==============================================================================
# Scenario 3: In-progress tasks are included
# ==============================================================================

def test_in_progress_tasks_are_included(cognitive_engine: SimpleCognitiveEngine, op_repo: InMemoryOperationalItemRepository):
    """
    3. In-progress tasks are included.
    """
    t1 = make_task(summary="Design new dashboard", owner_id="U_ALICE", status=OperationalItemStatus.OPEN)
    t2 = make_task(summary="Migrate legacy database schema", owner_id="U_ALICE", status=OperationalItemStatus.IN_PROGRESS)
    op_repo.save(t1)
    op_repo.save(t2)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    assert "You currently have 2 open tasks:" in answer.text
    assert "Design new dashboard — Open" in answer.text
    assert "Migrate legacy database schema — In Progress" in answer.text


# ==============================================================================
# Scenario 4: Completed tasks are excluded
# ==============================================================================

def test_completed_tasks_are_excluded(cognitive_engine: SimpleCognitiveEngine, op_repo: InMemoryOperationalItemRepository):
    """
    4. Completed tasks are excluded.
    """
    t_open = make_task(summary="Write documentation", owner_id="U_ALICE", status=OperationalItemStatus.OPEN)
    t_comp = make_task(summary="Review old PR", owner_id="U_ALICE", status=OperationalItemStatus.COMPLETED)
    t_canc = make_task(summary="Cancelled prototype", owner_id="U_ALICE", status=OperationalItemStatus.CANCELLED)
    op_repo.save(t_open)
    op_repo.save(t_comp)
    op_repo.save(t_canc)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    assert "You currently have 1 open task:" in answer.text
    assert "Write documentation — Open" in answer.text
    assert "Review old PR" not in answer.text
    assert "Cancelled prototype" not in answer.text


# ==============================================================================
# Scenario 5: Tasks assigned to other people are excluded
# ==============================================================================

def test_tasks_assigned_to_other_people_are_excluded(cognitive_engine: SimpleCognitiveEngine, op_repo: InMemoryOperationalItemRepository):
    """
    5. Tasks assigned to other people are excluded.
    """
    t_alice = make_task(summary="Alice's important task", owner_id="U_ALICE", status=OperationalItemStatus.OPEN)
    t_bob1 = make_task(summary="Bob's secret client work", owner_id="U_BOB", status=OperationalItemStatus.OPEN)
    t_bob2 = make_task(summary="Bob's internal bugfix", owner_id="U_BOB", status=OperationalItemStatus.IN_PROGRESS)
    op_repo.save(t_alice)
    op_repo.save(t_bob1)
    op_repo.save(t_bob2)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    assert "You currently have 1 open task:" in answer.text
    assert "Alice's important task" in answer.text
    assert "Bob's secret client work" not in answer.text
    assert "Bob's internal bugfix" not in answer.text


# ==============================================================================
# Scenario 6: Overdue and due-soon tasks are highlighted only when supported by actual dates
# ==============================================================================

def test_overdue_and_due_soon_highlighted_only_when_supported_by_actual_dates(
    cognitive_engine: SimpleCognitiveEngine,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    6. Overdue and due-soon tasks are highlighted only when supported by actual dates.
    """
    now = datetime.now(timezone.utc)
    overdue_date = now - timedelta(days=2)
    due_soon_date = now + timedelta(hours=8)
    future_date = now + timedelta(days=14)

    t_overdue = make_task(summary="Fix critical auth vulnerability", owner_id="U_ALICE", status=OperationalItemStatus.OPEN, due_at=overdue_date)
    t_due_soon = make_task(summary="Submit tax report", owner_id="U_ALICE", status=OperationalItemStatus.OPEN, due_at=due_soon_date)
    t_future = make_task(summary="Plan annual offsite", owner_id="U_ALICE", status=OperationalItemStatus.OPEN, due_at=future_date)
    t_no_date = make_task(summary="Organize bookmarks", owner_id="U_ALICE", status=OperationalItemStatus.OPEN, due_at=None)

    op_repo.save(t_overdue)
    op_repo.save(t_due_soon)
    op_repo.save(t_future)
    op_repo.save(t_no_date)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    # Verify task tags
    assert "[Overdue]" in answer.text
    assert "[Due soon]" in answer.text
    assert "Plan annual offsite — Open — Due: " in answer.text
    assert "Organize bookmarks — Open" in answer.text
    assert "Organize bookmarks — Open — Due" not in answer.text  # No fabricated due date!

    # Verify highlight alert
    assert "⚠️ You have 1 overdue task: 'Fix critical auth vulnerability'." in answer.text

    # Verify recommendation picks the overdue task with grounded reason
    assert "I recommend starting with 'Fix critical auth vulnerability' because it is overdue" in answer.text
    assert overdue_date.strftime("%Y-%m-%d") in answer.text


# ==============================================================================
# Scenario 7: No-task greeting returns a friendly response without fabricated tasks
# ==============================================================================

def test_no_task_greeting_returns_friendly_response_without_fabrication(
    cognitive_engine: SimpleCognitiveEngine,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    7. No-task greeting returns a friendly response without fabricated tasks.
    """
    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    assert "Good morning, Alice! 👋" in answer.text
    assert "You currently have no open tasks recorded." in answer.text
    assert "1." not in answer.text
    assert "recommend starting" not in answer.text


# ==============================================================================
# Scenario 8: Task retrieval failure does not produce a misleading empty-task response
# ==============================================================================

def test_task_retrieval_failure_does_not_produce_misleading_empty_task_response(
    cognitive_engine: SimpleCognitiveEngine,
):
    """
    8. Task retrieval failure does not produce a misleading empty-task response.
    """
    faulty_repo = MagicMock()
    faulty_repo.find_open_for_owner_or_name.side_effect = RuntimeError("Database connection timed out")

    # Inject faulty repo
    cognitive_engine._operational_item_repository = faulty_repo

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    q = Question(text="Good morning!", context=ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    assert "Good morning, Alice! 👋" in answer.text
    assert "I was unable to retrieve your morning task briefing right now. Please try again in a moment." in answer.text
    assert "no open tasks recorded" not in answer.text
    assert "0 open tasks" not in answer.text


# ==============================================================================
# Scenario 9: Greeting with a substantive question still answers the question normally
# ==============================================================================

def test_greeting_with_substantive_question_answers_question_normally(
    intent_router: SlackIntentRouter,
    mock_responder: MagicMock,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    9. Greeting with a substantive question still answers the question normally.
    """
    # User has tasks
    t = make_task(summary="Task in background", owner_id="U_ALICE")
    op_repo.save(t)

    msg = SlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Good morning! What are the high priority risks?",
        ts="1762128000.1",
        event_ts="1762128000.1",
    )

    intent_router.handle(msg)

    assert mock_responder.reply.called
    reply_text = mock_responder.reply.call_args[1]["text"]

    # Must answer substantive question normally without morning briefing task list
    assert "You currently have 1 open task:" not in reply_text
    assert "Would you like me to help you break it down" not in reply_text


# ==============================================================================
# Scenario 10: Ordinary farewell does not trigger a morning briefing
# ==============================================================================

def test_ordinary_farewell_does_not_trigger_morning_briefing(
    intent_router: SlackIntentRouter,
    mock_responder: MagicMock,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    10. Ordinary farewell does not trigger a morning briefing.
    """
    t = make_task(summary="Task that should not be listed on goodbye", owner_id="U_ALICE")
    op_repo.save(t)

    farewells = [
        "Goodbye!",
        "Bye POLIS",
        "See you tomorrow!",
        "Good night team",
    ]

    for farewell in farewells:
        mock_responder.reset_mock()
        msg = SlackMessage(
            user="U_ALICE",
            channel="D_ALICE",
            text=farewell,
            ts="1762128000.2",
            event_ts="1762128000.2",
        )
        intent_router.handle(msg)

        assert mock_responder.reply.called
        reply_text = mock_responder.reply.call_args[1]["text"]

        assert "You currently have" not in reply_text
        assert "open task" not in reply_text
        assert "Task that should not be listed" not in reply_text
        assert "Would you like me to help you break it down" not in reply_text


# ==============================================================================
# Scenario 11: Public-channel greeting does not disclose task details
# ==============================================================================

def test_public_channel_greeting_does_not_disclose_task_details(
    cognitive_engine: SimpleCognitiveEngine,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    11. Public-channel greeting does not disclose task details.
    """
    t = make_task(summary="Alice's confidential task", owner_id="U_ALICE")
    op_repo.save(t)

    # Public channel context
    public_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_GENERAL",
        thread_ts="100.1",
        channel_type="channel",
    )
    q = Question(text="Good morning!", context=public_ctx, target_user_name="Alice")

    answer = cognitive_engine.ask(q)

    # Greet warmly by name, but zero task disclosure in public channel
    assert "Good morning, Alice! 👋" in answer.text
    assert "Alice's confidential task" not in answer.text
    assert "open task" not in answer.text


# ==============================================================================
# Scenario 12: Task selection leads to useful next-step guidance without unauthorized status change
# ==============================================================================

def test_task_selection_provides_guidance_without_status_change(
    cognitive_engine: SimpleCognitiveEngine,
    op_repo: InMemoryOperationalItemRepository,
    mock_qa: MagicMock,
):
    """
    12. Task selection leads to useful next-step guidance without unauthorized task status changes.
    """
    task = make_task(
        summary="Finalize architectural proposal",
        owner_id="U_ALICE",
        owner_name="Alice",
        status=OperationalItemStatus.OPEN,
    )
    op_repo.save(task)

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        channel_type="im",
        history=[
            {"role": "user", "content": "Good morning!"},
            {"role": "assistant", "content": "You currently have 1 open task:\n1. Finalize architectural proposal — Open\n\nWould you like me to help you break it down into the first actionable steps?"},
        ],
    )

    q = Question(
        text="Help me break down Finalize architectural proposal into actionable steps",
        context=ctx,
        target_user_id="U_ALICE",
    )

    # Configure QA service to verify read evidence
    mock_qa.answer_from_evidence.return_value = Answer(
        text="Here is the breakdown for Finalize architectural proposal:\n1. Review component diagrams\n2. Draft deployment specification.",
        is_conversational=False,
    )

    answer = cognitive_engine.ask(q)

    # 1. Answer provides breakdown guidance
    assert "Finalize architectural proposal" in answer.text

    # 2. Crucial: Task status MUST remain OPEN! No unauthorized mutation
    reloaded_task = op_repo.find_by_id(task.identifier.graph_id)
    assert reloaded_task is not None
    assert reloaded_task.status == OperationalItemStatus.OPEN

    # 3. No new tasks created
    all_open = op_repo.find_open(item_type=OperationalItemType.TASK)
    assert len(all_open) == 1


# ==============================================================================
# Scenario 13: Missing display name uses a safe fallback
# ==============================================================================

def test_missing_display_name_uses_safe_fallback(
    cognitive_engine: SimpleCognitiveEngine,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    13. Missing display name uses a safe fallback.
    """
    ctx = ConversationContext(user_id="U_UNKNOWN_99", channel_id="D_UNKNOWN", thread_ts="100.1", channel_type="im")
    # No target_user_name, unknown user ID
    q = Question(text="Good morning!", context=ctx, target_user_name=None)

    answer = cognitive_engine.ask(q)

    # Must not say "Good morning, None!" or "Good morning, U_UNKNOWN_99!"
    assert answer.text.startswith("Good morning! 👋")
    assert "None" not in answer.text.split("\n")[0]
    assert "U_UNKNOWN_99" not in answer.text.split("\n")[0]


# ==============================================================================
# Scenario 14: Duplicate greetings do not duplicate tasks or create new workday sessions
# ==============================================================================

def test_duplicate_greetings_do_not_duplicate_tasks_or_sessions(
    activity_processor: ActivityProcessor,
    intent_router: SlackIntentRouter,
    workday_repo: InMemoryWorkdaySessionRepository,
    op_repo: InMemoryOperationalItemRepository,
    mock_responder: MagicMock,
):
    """
    14. Duplicate greetings do not duplicate tasks or create new workday sessions.
    """
    task = make_task(summary="Alice's daily task", owner_id="U_ALICE")
    op_repo.save(task)

    # First greeting at 09:00
    msg1 = SlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Good morning!",
        ts="1762128000.1",
        event_ts="1762128000.1",
        user_name="Alice",
    )
    activity_processor.process_message(msg1)
    intent_router.handle(msg1)

    session1 = workday_repo.find_active("U_ALICE")
    assert session1 is not None
    assert session1.status == WorkdaySessionStatus.ACTIVE
    first_started_at = session1.started_at
    tasks_count_after_first = len(op_repo.find_open(item_type=OperationalItemType.TASK))

    # Second greeting at 09:15
    msg2 = SlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Good morning POLIS!",
        ts="1762128900.2",
        event_ts="1762128900.2",
        user_name="Alice",
    )
    activity_processor.process_message(msg2)
    mock_responder.reset_mock()
    intent_router.handle(msg2)

    # Verify session was NOT duplicated and start timestamp preserved
    session2 = workday_repo.find_active("U_ALICE")
    assert session2 is not None
    assert session2.identifier.graph_id == session1.identifier.graph_id
    assert session2.started_at == first_started_at

    # Verify task count was NOT duplicated
    tasks_count_after_second = len(op_repo.find_open(item_type=OperationalItemType.TASK))
    assert tasks_count_after_second == tasks_count_after_first == 1

    # Verify responder replied with the briefing again
    assert mock_responder.reply.called
    assert "Alice's daily task" in mock_responder.reply.call_args[1]["text"]


# ==============================================================================
# Regression Test: Slack-thread scenario reproducing manual test failure
# ==============================================================================

def test_slack_thread_greeting_addressed_to_polis_triggers_task_briefing(
    cognitive_engine: SimpleCognitiveEngine,
    intent_router: SlackIntentRouter,
    mock_responder: MagicMock,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    Regression test reproducing the actual manual test failure:
    Input: authenticated user sends "Good morning!" in a Slack thread addressed to POLIS.

    Assert:
    1. The personalized briefing handler is invoked.
    2. The authenticated Slack user ID reaches task retrieval.
    3. The display name appears in the response.
    4. Actual open tasks appear in the response.
    5. The generic greeting-only response is not returned.
    6. Existing compound greeting and sign-off tests continue passing.
    """
    # Seed operational tasks for authenticated Slack user U_AKSHAT
    due_tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    task1 = make_task(
        summary="Audit production authentication tokens",
        owner_id="U_AKSHAT",
        owner_name="Akshat",
        status=OperationalItemStatus.OPEN,
        due_at=due_tomorrow,
    )
    task2 = make_task(
        summary="Optimize postgres query planner parameters",
        owner_id="U_AKSHAT",
        owner_name="Akshat",
        status=OperationalItemStatus.IN_PROGRESS,
    )
    # Seed task for another user to verify isolation
    task_other = make_task(
        summary="Other user's private task",
        owner_id="U_BOB",
        owner_name="Bob",
        status=OperationalItemStatus.OPEN,
    )
    op_repo.save(task1)
    op_repo.save(task2)
    op_repo.save(task_other)

    # Spy on _handle_morning_briefing and find_open_for_owner_or_name
    real_briefing = cognitive_engine._handle_morning_briefing
    briefing_spy = MagicMock(side_effect=real_briefing)
    cognitive_engine._handle_morning_briefing = briefing_spy

    real_find = op_repo.find_open_for_owner_or_name
    find_spy = MagicMock(side_effect=real_find)
    op_repo.find_open_for_owner_or_name = find_spy

    # Authenticated user sends "Good morning!" in a thread in a public channel
    msg = SlackMessage(
        user="U_AKSHAT",
        channel="C_PROJECT_TEAM",
        text="Good morning!",
        ts="1762128000.000200",
        event_ts="1762128000.000200",
        thread_ts="1762128000.000100",
        user_name="Akshat",
    )

    mock_responder.reset_mock()
    intent_router.handle(msg)

    # 1. Assert personalized briefing handler was invoked
    assert briefing_spy.called, "The personalized briefing handler was not invoked!"
    assert briefing_spy.call_count == 1

    # 2. Assert authenticated Slack user ID reached task retrieval
    assert find_spy.called, "OperationalItemRepository.find_open_for_owner_or_name was not called!"
    call_kwargs = find_spy.call_args.kwargs
    assert call_kwargs.get("owner_id") == "U_AKSHAT", (
        f"Expected owner_id='U_AKSHAT', got {call_kwargs.get('owner_id')}"
    )

    # 3. Assert responder was called and display name appears in response
    assert mock_responder.reply.called, "No Slack reply was sent!"
    reply_args = mock_responder.reply.call_args
    reply_text = reply_args[1].get("text", "")

    assert "Good morning, Akshat!" in reply_text, (
        f"Expected 'Good morning, Akshat!' in reply, got:\n{reply_text}"
    )

    # 4. Assert actual open tasks appear in response
    assert "You currently have 2 open tasks:" in reply_text
    assert "Audit production authentication tokens" in reply_text
    assert "Optimize postgres query planner parameters" in reply_text
    assert "Other user's private task" not in reply_text

    # 5. Assert generic greeting-only response is not returned
    assert reply_text != "Good morning!"
    assert reply_text != "Hello! How can I help you today?"
    assert "Would you like me to help you break it down into the first actionable steps?" in reply_text


@pytest.mark.asyncio
async def test_slack_socket_listener_thread_greeting_end_to_end(
    cognitive_engine: SimpleCognitiveEngine,
    activity_processor: ActivityProcessor,
    mock_responder: MagicMock,
    op_repo: InMemoryOperationalItemRepository,
    identity_service: MockIdentityDirectory,
):
    """
    End-to-end regression test through SlackSocketListener._handle_message():
    When an authenticated user sends 'Good morning!' in an established thread
    addressed to POLIS, the full listener pipeline executes:
    1. Activity detection records start of day.
    2. Intent router builds thread context with is_thread=True and user_id.
    3. Cognitive engine invokes morning briefing handler.
    4. Operational repository retrieves U_AKSHAT's tasks.
    5. Responder replies with personalized briefing in thread.
    """
    from connectors.slack.socket.listener import SlackSocketListener

    due_date = datetime.now(timezone.utc) + timedelta(days=3)
    task = make_task(
        summary="Implement security token rotation",
        owner_id="U_AKSHAT",
        owner_name="Akshat",
        status=OperationalItemStatus.OPEN,
        due_at=due_date,
    )
    op_repo.save(task)

    conv_repo = InMemoryConversationRepository()
    # Establish existing thread where POLIS already participated
    existing_thread_ctx = ConversationContext(
        user_id="U_AKSHAT",
        channel_id="C_TEAM_CHANNEL",
        thread_ts="1762128000.000100",
        history=[
            {"role": "user", "content": "Hello POLIS", "user_id": "U_AKSHAT"},
            {"role": "assistant", "content": "Hello! How can I assist you?", "user_id": "U_AKSHAT"},
        ],
        is_thread=True,
    )
    conv_repo.save(existing_thread_ctx)

    router = SlackIntentRouter(
        engine=cognitive_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=conv_repo,
        identity_service=identity_service,
        activity_detector=ActivityDetector(),
    )

    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler"), \
         patch("connectors.slack.socket.listener.SlackConnector"), \
         patch("connectors.slack.socket.listener.SlackClient"), \
         patch("connectors.slack.socket.listener.SlackResponder", return_value=mock_responder):

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=MagicMock(),
            activity_processor=activity_processor,
            conversation_repository=conv_repo,
            intent_router=router,
        )
        listener._responder = mock_responder
        listener._identity_service = identity_service
        listener._intent_router = router

        mock_settings = MagicMock()
        mock_settings.slack_bot_user_id = "U_BOT"
        mock_settings.reminder_timezone = "UTC"
        mock_settings.reminder_time_1 = "09:00"
        mock_settings.reminder_time_2 = "17:00"

        event = {
            "user": "U_AKSHAT",
            "channel": "C_TEAM_CHANNEL",
            "channel_type": "channel",
            "text": "Good morning!",
            "ts": "1762128000.000200",
            "thread_ts": "1762128000.000100",
        }

        mock_responder.reset_mock()
        with patch("connectors.slack.socket.listener.get_settings", return_value=mock_settings):
            await listener._handle_message(event)

        assert mock_responder.reply.called, "Expected reply from SlackSocketListener pipeline"
        call_kwargs = mock_responder.reply.call_args[1]
        assert call_kwargs["channel"] == "C_TEAM_CHANNEL"
        assert call_kwargs["thread_ts"] == "1762128000.000100"
        reply_text = call_kwargs["text"]

        assert "Good morning, Akshat!" in reply_text
        assert "Implement security token rotation" in reply_text
        assert "You currently have 1 open task:" in reply_text
        assert reply_text != "Good morning!"


# ==============================================================================
# Scenario 17: Live Slack greeting regression test reproducing actual manual test
# ==============================================================================

@pytest.mark.asyncio
async def test_live_slack_greeting_personalized_briefing_regression(
    cognitive_engine: SimpleCognitiveEngine,
    activity_processor: ActivityProcessor,
    mock_responder: MagicMock,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    Live Slack greeting regression test reproducing actual manual test:
    Input:
    Authenticated Slack user ID: U_TEST
    Display name: Akshat Tripathi
    Message: "Good Morning!"

    Assert:
    - Final Slack response begins with "Good morning, Akshat Tripathi!"
    - Generic response "I'm ready to help with whatever you need" is not returned.
    - The correct user's tasks are retrieved and listed.
    - No other user's tasks are included.
    - Existing thread, public-channel, compound greeting, and sign-off tests still pass.
    """
    from connectors.slack.socket.listener import SlackSocketListener

    # 1. Identity service setup: user U_TEST resolves to "Akshat Tripathi"
    identity_directory = MockIdentityDirectory({
        "U_TEST": "Akshat Tripathi",
        "U_OTHER": "Other Colleague",
        "U_BOT": "POLIS",
    })

    # 2. Seed tasks: U_TEST has 2 tasks, U_OTHER has 1 task
    due_date = datetime.now(timezone.utc) + timedelta(days=2)
    task_test_1 = make_task(
        summary="Review cloud infrastructure security audit",
        owner_id="U_TEST",
        owner_name="Akshat Tripathi",
        status=OperationalItemStatus.OPEN,
        due_at=due_date,
    )
    task_test_2 = make_task(
        summary="Configure Slack bot socket mode connection pool",
        owner_id="U_TEST",
        owner_name="Akshat Tripathi",
        status=OperationalItemStatus.IN_PROGRESS,
    )
    task_other = make_task(
        summary="Colleague's confidential financial report",
        owner_id="U_OTHER",
        owner_name="Other Colleague",
        status=OperationalItemStatus.OPEN,
    )
    op_repo.save(task_test_1)
    op_repo.save(task_test_2)
    op_repo.save(task_other)

    conv_repo = InMemoryConversationRepository()
    # Establish existing thread context where POLIS was addressed
    thread_ctx = ConversationContext(
        user_id="U_TEST",
        channel_id="C_TEST_CHANNEL",
        thread_ts="1762129000.000100",
        history=[
            {"role": "user", "content": "Hello POLIS", "user_id": "U_TEST"},
            {"role": "assistant", "content": "Hello! How can I help you?", "user_id": "U_TEST"},
        ],
        is_thread=True,
    )
    conv_repo.save(thread_ctx)

    router = SlackIntentRouter(
        engine=cognitive_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=conv_repo,
        identity_service=identity_directory,
        activity_detector=ActivityDetector(),
    )

    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler"), \
         patch("connectors.slack.socket.listener.SlackConnector"), \
         patch("connectors.slack.socket.listener.SlackClient"), \
         patch("connectors.slack.socket.listener.SlackResponder", return_value=mock_responder):

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=MagicMock(),
            activity_processor=activity_processor,
            conversation_repository=conv_repo,
            intent_router=router,
        )
        listener._responder = mock_responder
        listener._identity_service = identity_directory
        listener._intent_router = router

        mock_settings = MagicMock()
        mock_settings.slack_bot_user_id = "U_BOT"
        mock_settings.reminder_timezone = "UTC"
        mock_settings.reminder_time_1 = "09:00"
        mock_settings.reminder_time_2 = "17:00"

        # The message as sent by the user in Slack (raw user ID, no pre-populated user_name)
        event = {
            "user": "U_TEST",
            "channel": "C_TEST_CHANNEL",
            "channel_type": "channel",
            "text": "Good Morning!",
            "ts": "1762129000.000200",
            "thread_ts": "1762129000.000100",
        }

        mock_responder.reset_mock()
        with patch("connectors.slack.socket.listener.get_settings", return_value=mock_settings):
            await listener._handle_message(event)

        assert mock_responder.reply.called, "Expected reply from listener pipeline"
        call_kwargs = mock_responder.reply.call_args[1]
        reply_text = call_kwargs["text"]

        # Assert:
        # - Final Slack response begins with "Good morning, Akshat Tripathi!"
        assert reply_text.startswith("Good morning, Akshat Tripathi!"), (
            f"Expected response to begin with 'Good morning, Akshat Tripathi!', got:\n{reply_text}"
        )
        assert reply_text.startswith("Good morning, Akshat Tripathi! 👋")

        # - Generic response "I'm ready to help with whatever you need" is not returned.
        assert "I'm ready to help with whatever you need" not in reply_text
        assert "Good Morning! I'm ready to help with whatever you need." not in reply_text

        # - The correct user's tasks are retrieved and listed.
        assert "You currently have 2 open tasks:" in reply_text
        assert "Review cloud infrastructure security audit" in reply_text
        assert "Configure Slack bot socket mode connection pool" in reply_text

        # - No other user's tasks are included.
        assert "Colleague's confidential financial report" not in reply_text
        assert "Other Colleague" not in reply_text


def test_intent_router_raw_user_id_resolves_authenticated_sender_display_name(
    cognitive_engine: SimpleCognitiveEngine,
    mock_responder: MagicMock,
    op_repo: InMemoryOperationalItemRepository,
):
    """
    Direct test on SlackIntentRouter: when message.user_name is raw user ID 'U_TEST',
    SlackIntentRouter resolves 'Akshat Tripathi' via identity service and returns
    the personalized morning briefing beginning with 'Good morning, Akshat Tripathi!'.
    """
    identity_directory = MockIdentityDirectory({
        "U_TEST": "Akshat Tripathi",
        "U_OTHER": "Other Colleague",
        "U_BOT": "POLIS",
    })

    task = make_task(
        summary="Implement security token rotation",
        owner_id="U_TEST",
        owner_name="Akshat Tripathi",
        status=OperationalItemStatus.OPEN,
    )
    task_other = make_task(
        summary="Other user's private task",
        owner_id="U_OTHER",
        owner_name="Other Colleague",
        status=OperationalItemStatus.OPEN,
    )
    op_repo.save(task)
    op_repo.save(task_other)

    conv_repo = InMemoryConversationRepository()
    thread_ctx = ConversationContext(
        user_id="U_TEST",
        channel_id="D_TEST",
        thread_ts="100.1",
        history=[],
        channel_type="im",
    )
    conv_repo.save(thread_ctx)

    router = SlackIntentRouter(
        engine=cognitive_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=conv_repo,
        identity_service=identity_directory,
        activity_detector=ActivityDetector(),
    )

    # message.user_name is raw user ID 'U_TEST' (or empty)
    msg = SlackMessage(
        user="U_TEST",
        channel="D_TEST",
        text="Good Morning!",
        ts="100.2",
        event_ts="100.2",
        thread_ts="100.1",
        user_name="U_TEST",
    )

    mock_responder.reset_mock()
    router.handle(msg)

    assert mock_responder.reply.called
    reply_text = mock_responder.reply.call_args[1]["text"]

    assert reply_text.startswith("Good morning, Akshat Tripathi!")
    assert "I'm ready to help with whatever you need" not in reply_text
    assert "Implement security token rotation" in reply_text
    assert "Other user's private task" not in reply_text
