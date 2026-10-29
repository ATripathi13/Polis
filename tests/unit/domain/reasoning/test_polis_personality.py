"""
Comprehensive automated regression test suite for POLIS human-like team personality.

Covers all 14 required behavioral cases:
1. Compliment receives a brief, natural acknowledgement before anything else.
2. Thanks receives a proportionate response without forced follow-up questions.
3. Frustration is acknowledged with empathy and constructive action, without defensiveness.
4. Casual greetings do not trigger operational agents or calendar workflows.
5. Farewells are not met with unsolicited task suggestions.
6. A technical request retains the existing retrieval and routing behavior.
7. Reminder and calendar requests still reach their correct handlers.
8. Assessment / operational workflows are not triggered by unrelated keyword matches.
9. Relevant history improves continuity when available.
10. Missing history does not cause fabricated memories.
11. Responses do not expose another sender's private context (sender isolation).
12. Tool results and action completion claims remain strictly truthful.
13. Existing structured output contracts are preserved.
14. The behavior works through the existing Slack response pipeline and shared cognitive engine.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from application.calendar import (
    AudienceResolutionService,
    CalendarAgent,
    CalendarService,
)
from application.cognitive import SimpleCognitiveEngine
from domain.calendar import (
    CalendarAudienceType,
    CalendarEntryType,
    CalendarReminderPolicy,
    InMemoryCalendarRepository,
)
from domain.reasoning import (
    Answer,
    ConversationContext,
    Question,
    SimpleReasoningService,
)
from domain.reasoning.communication_style import (
    COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS,
    NO_INFORMATION_RESPONSE,
)
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)
from domain.common.identifier import Identifier
from infrastructure.database.conversation_repository import (
    InMemoryConversationRepository,
)
from infrastructure.llm.knowledge_understanding import (
    LLMKnowledgeUnderstanding,
)
from infrastructure.llm.operational_understanding import (
    LLMOperationalUnderstanding,
)
from infrastructure.llm.organizational_intent_understanding import (
    LLMOrganizationalIntentUnderstanding,
)


class MockLLMClient:
    def __init__(self, response: str = "Default response"):
        self.response = response
        self.last_prompt: str | None = None
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        self.prompts.append(prompt)
        return self.response


# ==============================================================================
# 1. Compliment receives a brief, natural acknowledgement
# ==============================================================================

def test_compliment_receives_natural_acknowledgement():
    mock_llm = MockLLMClient(
        "Haha, glad I could impress you! We've made good progress on this. Want to tackle the remaining items next?"
    )
    comm_repo = InMemoryCommunicationRepository()
    service = SimpleReasoningService(
        repository=None,
        communication_repository=comm_repo,
        llm_client=mock_llm,
    )

    q = Question(text="You're the smartest bot. You impressed me.")
    answer = service.answer(q)

    # 1. Prompt includes shared human-like personality and compliment instructions
    assert mock_llm.last_prompt is not None
    assert "Acknowledge the compliment warmly and naturally before anything else" in mock_llm.last_prompt
    assert "Avoid launching immediately into capability lists" in mock_llm.last_prompt

    # 2. Answer semantic qualities
    assert answer.confidence == 0.0
    assert answer.is_conversational is True
    assert "glad i could impress you" in answer.text.lower()
    # Does not contain generic AI assistant cliches
    assert "how may i assist you" not in answer.text.lower()
    assert "as an ai" not in answer.text.lower()


# ==============================================================================
# 2. Thanks receives a proportionate response
# ==============================================================================

def test_thanks_receives_proportionate_response():
    mock_llm = MockLLMClient("Perfect, glad it worked!")
    comm_repo = InMemoryCommunicationRepository()
    service = SimpleReasoningService(
        repository=None,
        communication_repository=comm_repo,
        llm_client=mock_llm,
    )

    q = Question(text="Thanks, that worked.")
    answer = service.answer(q)

    assert mock_llm.last_prompt is not None
    assert "Respond proportionately" in mock_llm.last_prompt
    assert "Do not automatically add another question or pitch additional services" in mock_llm.last_prompt

    assert answer.confidence == 0.0
    assert answer.is_conversational is True
    assert "glad it worked" in answer.text.lower()
    # Does not offer unsolicited service menus
    assert "here are five ways" not in answer.text.lower()
    assert "is there anything else" not in answer.text.lower()


# ==============================================================================
# 3. Frustration is acknowledged without defensiveness
# ==============================================================================

def test_frustration_acknowledged_without_defensiveness():
    mock_llm = MockLLMClient(
        "Yeah, that's frustrating, especially after fixing it already. "
        "Let's find out why it's recurring instead of applying another temporary fix."
    )
    comm_repo = InMemoryCommunicationRepository()
    service = SimpleReasoningService(
        repository=None,
        communication_repository=comm_repo,
        llm_client=mock_llm,
    )

    q = Question(text="This is the third time the same bug has appeared.")
    answer = service.answer(q)

    assert mock_llm.last_prompt is not None
    assert "Acknowledge the frustration with empathy" in mock_llm.last_prompt
    assert "without being defensive, blaming the user, or over-apologizing" in mock_llm.last_prompt

    assert answer.confidence == 0.0
    assert answer.is_conversational is True
    assert "frustrating" in answer.text.lower()
    assert "recurring" in answer.text.lower()


# ==============================================================================
# 4. Casual greetings do not trigger operational agents
# ==============================================================================

def test_casual_greetings_do_not_trigger_operational_agents():
    # Verify that CalendarAgent does not treat casual greeting as a calendar event
    cal_repo = InMemoryCalendarRepository()
    mock_provider = MagicMock()
    audience_service = AudienceResolutionService(
        directory_provider=mock_provider,
        organization_channel_id="C_MAIN",
    )
    cal_service = CalendarService(
        repository=cal_repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )
    cal_agent = CalendarAgent(service=cal_service)

    cal_res = cal_agent.handle_message("Hey, what's up?", user_id="U1")
    assert cal_res is None  # Not handled by calendar

    # Verify that SimpleReasoningService handles greeting conversationally
    mock_llm = MockLLMClient("Hey! All good here. What are we working on today?")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )
    ans = service.answer(Question(text="Hey, what's up?"))
    assert mock_llm.last_prompt is not None
    assert "Casual conversation" in mock_llm.last_prompt
    assert "All good here" in ans.text


# ==============================================================================
# 5. Farewells are not met with unsolicited task suggestions
# ==============================================================================

def test_farewells_not_met_with_unsolicited_task_suggestions():
    mock_llm = MockLLMClient("Sounds good. We'll pick it up next time.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )

    q = Question(text="That's all for today.")
    answer = service.answer(q)

    assert mock_llm.last_prompt is not None
    assert "Do not force another task or question when an exchange is naturally ending" in mock_llm.last_prompt
    assert "Sounds good" in answer.text
    # Does not force another task or numbered list
    assert "1." not in answer.text
    assert "?" not in answer.text


# ==============================================================================
# 6. A technical request retains the existing routing behavior
# ==============================================================================

def test_technical_request_retains_existing_routing_behavior():
    comm_repo = InMemoryCommunicationRepository()
    comm = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-tech-1",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="U_ENG"),
            display_name="Engineer Dave",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C_TECH"),
            name="tech-talk",
            channel_type="public",
        ),
        content=Content(body="We use PostgreSQL as our database and asyncpg driver on port 5432."),
    )
    comm.created_at = datetime.now(timezone.utc)
    comm_repo.save(comm)

    mock_llm = MockLLMClient("We use PostgreSQL with asyncpg on port 5432.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=comm_repo,
        llm_client=mock_llm,
    )

    q = Question(text="What database and driver do we use?")
    answer = service.answer(q)

    assert answer.confidence == 0.8
    assert len(answer.evidence) == 1
    assert "PostgreSQL" in answer.text
    assert mock_llm.last_prompt is not None
    assert "Relevant organizational communications:" in mock_llm.last_prompt


# ==============================================================================
# 7. Reminder and calendar requests still reach their correct handlers
# ==============================================================================

def test_reminder_and_calendar_requests_reach_handlers():
    # 1. Calendar request reaches CalendarAgent
    cal_repo = InMemoryCalendarRepository()
    mock_provider = MagicMock()
    mock_provider.resolve_user_id.return_value = "U_TARGET"
    mock_provider.get_organization_channel_id.return_value = "C_MAIN"
    audience_service = AudienceResolutionService(
        directory_provider=mock_provider,
        organization_channel_id="C_MAIN",
    )
    cal_service = CalendarService(
        repository=cal_repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )
    cal_agent = CalendarAgent(service=cal_service)

    msg = "schedule activity 'Architecture Review' on 2026-11-20 15:00 for organization"
    cal_res = cal_agent.handle_message(msg, user_id="U_CREATOR")
    assert cal_res is not None
    assert "Successfully scheduled" in cal_res

    # 2. Reminder command recognized by clean text parsing
    from connectors.slack.routing import clean_slack_text
    bot_id = "U_BOT"
    assert clean_slack_text(f"<@{bot_id}> remind @alice to update docs", bot_id) == "remind @alice to update docs"
    assert clean_slack_text(f"<@{bot_id}> stop reminders", bot_id) == "stop reminders"


# ==============================================================================
# 8. Assessment guidance is not triggered by unrelated keyword matches
# ==============================================================================

def test_assessment_not_triggered_by_unrelated_keywords():
    # A conversational compliment or observation mentioning "assessment" or "evaluating"
    # must not trigger an operational workflow.
    cal_repo = InMemoryCalendarRepository()
    cal_agent = CalendarAgent(
        service=CalendarService(
            repository=cal_repo,
            audience_service=MagicMock(),
            reminder_policy=CalendarReminderPolicy(offset_hours=15),
            default_timezone="Asia/Kolkata",
        )
    )

    # Compliment mentioning evaluation
    msg = "Your assessment of the retry problem yesterday was really sharp!"
    assert cal_agent.handle_message(msg, user_id="U1") is None

    mock_llm = MockLLMClient("Thanks! Glad the analysis helped resolve the retry problem.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )
    ans = service.answer(Question(text=msg))
    assert ans.confidence == 0.0
    assert ans.is_conversational is True
    assert "helped resolve" in ans.text


# ==============================================================================
# 9. Relevant history improves continuity when available
# ==============================================================================

def test_relevant_history_improves_continuity():
    mock_llm = MockLLMClient("We were debugging the listener filter. Let's check the router next.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="1234.56",
        history=[
            {"role": "user", "content": "Can you check the listener status?"},
            {"role": "assistant", "content": "The listener is active, but events might be filtered before reaching the router."},
        ],
    )

    q = Question(text="Let's continue where we left off.", context=ctx)
    answer = service.answer(q)

    assert mock_llm.last_prompt is not None
    assert "Recent conversation history for this thread:" in mock_llm.last_prompt
    assert "The listener is active, but events might be filtered" in mock_llm.last_prompt
    assert answer.confidence == 0.0
    assert answer.is_conversational is True
    assert "debugging the listener filter" in answer.text


# ==============================================================================
# 10. Missing history does not cause fabricated memories
# ==============================================================================

def test_missing_history_does_not_cause_fabricated_memories():
    mock_llm = MockLLMClient("What task would you like to continue? Can you share a little more context?")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )

    ctx = ConversationContext(
        user_id="U_BOB",
        channel_id="C_DEV",
        thread_ts="1234.99",
        history=[],
    )

    q = Question(text="Let's continue where we left off.", context=ctx)
    answer = service.answer(q)

    assert mock_llm.last_prompt is not None
    assert "Recent conversation history for this thread:" not in mock_llm.last_prompt
    assert "Do not invent past tasks or conversations that are not in the context" in mock_llm.last_prompt
    assert "Can you share a little more" in answer.text


# ==============================================================================
# 11. Responses do not expose another sender's private context
# ==============================================================================

def test_sender_isolation_prevents_leaking_private_context():
    # Context contains mixed user messages (e.g. from a shared channel structure)
    ctx = ConversationContext(
        user_id="U_CURRENT",
        channel_id="D_PRIVATE",
        thread_ts="100.1",
        history=[
            {"role": "user", "user_id": "U_SECRET_USER", "content": "My private secret project is Apollo."},
            {"role": "user", "user_id": "U_CURRENT", "content": "What was I working on?"},
        ],
    )

    formatted = SimpleReasoningService._format_conversation_history(
        ctx,
        current_user_id="U_CURRENT",
    )

    # U_SECRET_USER's private message MUST be excluded
    assert "Apollo" not in formatted
    assert "What was I working on?" in formatted


# ==============================================================================
# 12. Tool results and action completion claims remain truthful
# ==============================================================================

def test_action_completion_claims_remain_truthful():
    cal_repo = InMemoryCalendarRepository()
    mock_provider = MagicMock()
    mock_provider.resolve_user_id.return_value = "U_CREATOR"
    mock_provider.get_organization_channel_id.return_value = "C_MAIN"
    audience_service = AudienceResolutionService(
        directory_provider=mock_provider,
        organization_channel_id="C_MAIN",
    )
    cal_service = CalendarService(
        repository=cal_repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )
    cal_agent = CalendarAgent(service=cal_service)

    # Attempting to cancel a non-existent entry MUST NOT say "Done! I've cancelled it"
    res = cal_agent.handle_message("cancel event NON_EXISTENT_ID", user_id="U_CREATOR")
    assert res is not None
    assert "couldn't find" in res.lower()
    assert "Done! I've cancelled it" not in res

    # Creating a real entry actually confirms completion truthfully
    res_success = cal_agent.handle_message(
        "schedule activity 'Sprint Review' on 2026-11-25 10:00 for organization",
        user_id="U_CREATOR",
    )
    assert "Done! I've added it to the calendar." in res_success
    # Verified actually in the repository
    assert len(cal_repo.list_entries(
        start_range=datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc),
        end_range=datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc),
    )) == 1


# ==============================================================================
# 13. Existing structured output contracts are preserved
# ==============================================================================

def test_structured_output_contracts_preserved():
    mock_client = MagicMock()
    mock_client.generate.return_value = '{"is_operational": false}'
    op = LLMOperationalUnderstanding(mock_client)
    op.analyze("Deploy service to staging")
    prompt = mock_client.generate.call_args[0][0]
    assert "Return ONLY valid JSON in this exact structure:" in prompt
    assert '"is_operational": true' in prompt

    mock_client.generate.return_value = '{"is_knowledge": true}'
    kw = LLMKnowledgeUnderstanding(mock_client)
    kw.analyze("Policy document updated")
    prompt_kw = mock_client.generate.call_args[0][0]
    assert "Return ONLY valid JSON in this exact structure:" in prompt_kw

    mock_client.generate.return_value = '{"has_intent": false, "intent_type": null, "confidence": 0.0, "explanation": null}'
    intent = LLMOrganizationalIntentUnderstanding(mock_client)
    intent.analyze("Some text")
    prompt_intent = mock_client.generate.call_args[0][0]
    assert "Return ONLY valid JSON in this exact structure:" in prompt_intent


# ==============================================================================
# 14. Behavior works through the existing Slack response pipeline and cognitive engine
# ==============================================================================

def test_behavior_works_through_slack_and_shared_pipeline():
    # Set up mock pipeline components
    mock_pipeline = MagicMock()
    mock_llm = MockLLMClient("Haha, glad I could impress you! Ready for what's next.")
    comm_repo = InMemoryCommunicationRepository()
    reasoning_service = SimpleReasoningService(
        repository=None,
        communication_repository=comm_repo,
        llm_client=mock_llm,
    )

    cognitive_engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=reasoning_service,
    )

    conv_repo = InMemoryConversationRepository()
    mock_responder = MagicMock()
    mock_connector = MagicMock()

    from engines.slack.router.slack_intent_router import SlackIntentRouter
    from engines.slack.dto import SlackMessage as ActivitySlackMessage

    mock_identity_service = MagicMock()
    mock_identity_service.get_workspace_users.return_value = []

    intent_router = SlackIntentRouter(
        engine=cognitive_engine,
        responder=mock_responder,
        connector=mock_connector,
        conversation_repository=conv_repo,
        identity_service=mock_identity_service,
    )

    message = ActivitySlackMessage(
        user="U_ALICE",
        user_name="Alice",
        channel="D012345",
        text="You're the smartest bot. You impressed me.",
        ts="1700000000.000100",
        event_ts="1700000000.000100",
    )

    intent_router.handle(message)

    # 1. Responder called with natural human-like response
    mock_responder.reply.assert_called_once()
    reply_args = mock_responder.reply.call_args[1]
    assert reply_args["channel"] == "D012345"
    assert "glad i could impress you" in reply_args["text"].lower()

    # 2. Conversation repository updated with the exchange
    saved_ctx = conv_repo.get("D012345", "1700000000.000100")
    assert saved_ctx is not None
    assert len(saved_ctx.history) == 2
    assert saved_ctx.history[0]["content"] == "You're the smartest bot. You impressed me."
    assert "glad i could impress you" in saved_ctx.history[1]["content"].lower()

def test_sender_isolation_excludes_unscoped_assistant_history_in_private_dm():
    ctx = ConversationContext(
        user_id="U_CURRENT",
        channel_id="D_PRIVATE",
        thread_ts="100.1",
        history=[
            {
                "role": "user",
                "user_id": "U_SECRET_USER",
                "content": "My private secret project is Apollo.",
            },
            {
                "role": "assistant",
                "content": "Your private project Apollo is confidential.",
            },
            {
                "role": "user",
                "user_id": "U_CURRENT",
                "content": "What were we discussing?",
            },
        ],
    )

    formatted = SimpleReasoningService._format_conversation_history(
        ctx,
        current_user_id="U_CURRENT",
    )

    assert "Apollo" not in formatted
    assert "confidential" not in formatted
    assert "What were we discussing?" in formatted


# ==============================================================================
# 15. Correction A: Consistent, Honest POLIS Identity Across All Prompts
# ==============================================================================

def test_consistent_honest_identity_in_all_prompts():
    """Verify POLIS never claims to be a human employee and uses consistent teammate identity."""
    from domain.reasoning.communication_style import COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS

    # 1. No prompt describes POLIS as a literal human employee
    assert "human employee" not in COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS.lower()
    assert "socially intelligent, capable teammate" in COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS

    # 2. Reasoning service prompts use consistent identity
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=MockLLMClient("test"),
    )
    conv_prompt = service._build_conversational_prompt(Question(text="hello"))
    assert "human employee" not in conv_prompt.lower()
    assert "You are POLIS, a socially intelligent, capable teammate and organizational assistant." in conv_prompt


# ==============================================================================
# 16. Correction B: Separate Conversational Confidence from Factual Confidence
# ==============================================================================

def test_confidence_distinguishes_social_greeting_without_evidence():
    """Social greeting without evidence returns confidence=0.0 and is_conversational=True."""
    mock_llm = MockLLMClient("Good morning! Ready when you are.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )
    answer = service.answer(Question(text="Good morning!"))
    assert answer.confidence == 0.0
    assert answer.is_conversational is True
    assert answer.evidence == []
    assert "good morning" in answer.text.lower()


def test_confidence_distinguishes_valid_continuation_with_history():
    """Thread continuation with available history returns confidence=0.0 and is_conversational=True."""
    mock_llm = MockLLMClient("Let's pick up with the router configuration.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        history=[
            {"role": "user", "content": "What was the previous step?", "user_id": "U_ALICE"},
            {"role": "assistant", "content": "We finished configuring the listener.", "user_id": "U_ALICE"},
        ],
    )
    answer = service.answer(Question(text="What should we do next?", context=ctx))
    assert answer.confidence == 0.0
    assert answer.is_conversational is True
    assert answer.evidence == []
    assert "router" in answer.text.lower()


def test_confidence_distinguishes_organizational_question_without_evidence():
    """Organizational questions without evidence return confidence=0.0 and is_conversational=False without manufacturing facts."""
    mock_llm = MockLLMClient("Manufactured fact: Vacation policy allows 50 days.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=mock_llm,
    )
    answer = service.answer(Question(text="What is our company vacation policy?"))
    # Must NOT call LLM to hallucinate or manufacture organizational facts
    assert answer.confidence == 0.0
    assert answer.is_conversational is False
    assert answer.evidence == []
    assert "I don't have enough information to answer that confidently." in answer.text
    assert mock_llm.last_prompt is None  # LLM was not called


def test_confidence_distinguishes_grounded_organizational_answer():
    """Evidence-grounded organizational answers return confidence=0.8 and is_conversational=False."""
    comm_repo = InMemoryCommunicationRepository()
    comm = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-apollo-1",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="U_ALICE"),
            display_name="Alice",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C_MAIN"),
            name="general",
            channel_type="public",
        ),
        content=Content(body="Project Apollo scheduled release date is November 15."),
    )
    comm.created_at = datetime.now(timezone.utc)
    comm_repo.save(comm)

    mock_llm = MockLLMClient("Project Apollo is scheduled to release on November 15.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=comm_repo,
        llm_client=mock_llm,
    )
    answer = service.answer(Question(text="What is the scheduled release for Project Apollo?"))
    assert answer.confidence == 0.8
    assert answer.is_conversational is False
    assert len(answer.evidence) > 0
    assert "November 15" in answer.text


def test_confidence_distinguishes_llm_failure_empty_and_invalid():
    """LLM failures or empty/invalid responses return confidence=0.0 and is_conversational=False."""
    class FailingLLM:
        def generate(self, prompt: str) -> str:
            raise RuntimeError("API timeout")

    service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=FailingLLM(),
    )
    answer_fail = service.answer(Question(text="Hello!"))
    assert answer_fail.confidence == 0.0
    assert answer_fail.is_conversational is False
    assert "I don't have enough information" in answer_fail.text

    empty_service = SimpleReasoningService(
        repository=None,
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=MockLLMClient(""),
    )
    answer_empty = empty_service.answer(Question(text="Hello!"))
    assert answer_empty.confidence == 0.0
    assert answer_empty.is_conversational is False
    assert "I don't have enough information" in answer_empty.text


# ==============================================================================
# 17. Correction C: Harden Conversation-History Privacy
# ==============================================================================

def test_privacy_user_a_private_exchange_not_visible_to_user_b():
    """User A's private question and assistant response are not visible to User B."""
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE_DM",
        thread_ts="100.1",
        channel_type="im",
    ).add_exchange("Alice's confidential salary question", "Salary details for Alice")

    formatted_for_bob = SimpleReasoningService._format_conversation_history(
        ctx,
        current_user_id="U_BOB",
    )
    assert formatted_for_bob == ""
    assert "Alice" not in formatted_for_bob
    assert "Salary" not in formatted_for_bob


def test_privacy_user_a_history_not_inherited_by_user_b_in_new_dm():
    """User A's private history is not inherited by User B in a new DM thread."""
    repo = InMemoryConversationRepository()
    alice_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_SHARED_DM",
        thread_ts="100.1",
        channel_type="im",
    ).add_exchange("Alice's secret", "Alice's secret answer")
    repo.save(alice_ctx)

    bob_latest = repo.get_latest("D_SHARED_DM", user_id="U_BOB")
    assert bob_latest is None  # User B inherits nothing from User A!


def test_privacy_user_own_dm_history_remains_available():
    """A user's own DM history remains available to that same user."""
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE_DM",
        thread_ts="100.1",
        channel_type="im",
    ).add_exchange("Where is the deployment doc?", "It is in /docs/deploy.md")

    formatted = SimpleReasoningService._format_conversation_history(
        ctx,
        current_user_id="U_ALICE",
    )
    assert "Where is the deployment doc?" in formatted
    assert "It is in /docs/deploy.md" in formatted
    assert "User: Where is the deployment doc?" in formatted
    assert "POLIS: It is in /docs/deploy.md" in formatted


def test_shared_channel_thread_continuity_with_multi_user_attribution():
    """Shared-channel follow-ups from a different user preserve legitimate thread continuity without misattribution."""
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_PUBLIC_DEV",
        thread_ts="200.1",
        channel_type="channel",
    ).add_exchange(
        user_message="Should we deploy v2 today?",
        assistant_message="Tests are passing, but waiting on QA signoff.",
        user_id="U_ALICE",
    )

    formatted_for_bob = SimpleReasoningService._format_conversation_history(
        ctx,
        current_user_id="U_BOB",
    )
    assert "User (U_ALICE): Should we deploy v2 today?" in formatted_for_bob
    assert "POLIS: Tests are passing, but waiting on QA signoff." in formatted_for_bob


def test_privacy_missing_or_incomplete_metadata_fails_safely():
    """Empty, missing, or incomplete sender metadata fails safely."""
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_PRIVATE",
        thread_ts="300.1",
        history=[
            {"role": "user", "content": "Unattributed message without user_id"},
            {"role": "assistant", "content": "Unattributed assistant reply"},
        ],
    )
    formatted = SimpleReasoningService._format_conversation_history(
        ctx,
        current_user_id="U_ALICE",
    )
    assert formatted == ""  # Fails safe by omitting unscoped history

    formatted_none = SimpleReasoningService._format_conversation_history(
        ctx,
        current_user_id=None,
    )
    assert formatted_none == ""


def test_deduplication_prevents_duplicate_exchanges_in_conversation_context():
    """Calling add_exchange with the same exchange does not persist duplicate entries."""
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
    )
    ctx1 = ctx.add_exchange("Hello POLIS", "Hello Alice!")
    assert len(ctx1.history) == 2

    # Second call with identical exchange
    ctx2 = ctx1.add_exchange("Hello POLIS", "Hello Alice!")
    assert len(ctx2.history) == 2  # Not duplicated!

def test_mixed_thanks_and_factual_request_is_not_classified_as_social():
    """A social cue must not override a substantive organizational question."""
    assert not SimpleReasoningService._is_conversational_query(
        "Thanks, what's the project deadline?"
    )

def test_mixed_thanks_and_launch_date_question_is_not_classified_as_social():
    """A factual date question remains factual even when prefixed with thanks."""
    assert not SimpleReasoningService._is_conversational_query(
        "Thanks, when is the launch?"
    )
