"""
Unit tests for Stage 3 Cognitive Orchestration in SimpleCognitiveEngine.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from application.cognitive import CognitivePlanner, SimpleCognitiveEngine
from domain.reasoning.value_objects.answer import Answer
from domain.reasoning.value_objects.conversation_context import ConversationContext
from domain.reasoning.value_objects.question import Question


def test_simple_cognitive_engine_activity_fast_path():
    """Deterministic activity questions are answered immediately without planner execution."""
    pipeline = MagicMock()
    qa = MagicMock()
    activity_service = MagicMock()
    expected_answer = Answer(text="Alice is currently working.", confidence=1.0)
    activity_service.answer.return_value = expected_answer

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        activity_question_service=activity_service,
    )

    q = Question(text="Is Alice working?")
    ans = engine.ask(q)

    assert ans == expected_answer
    activity_service.answer.assert_called_once_with(q)
    qa.answer.assert_not_called()


def test_simple_cognitive_engine_missing_info_requests_clarification():
    """When a schedule request lacks date and time, the engine returns clarification and pending operation."""
    pipeline = MagicMock()
    qa = MagicMock()

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    q = Question(text="Schedule a meeting called Architecture Sync with Bob", context=ctx, target_user_id="U_ALICE")

    ans = engine.ask(q)

    assert "date and time" in ans.text.lower()
    assert ans.is_conversational is True
    assert ans.pending_operation is not None
    assert ans.pending_operation["user_id"] == "U_ALICE"
    assert "date" in ans.pending_operation["missing_fields"]
    assert "time" in ans.pending_operation["missing_fields"]


def test_simple_cognitive_engine_pending_operation_cancel():
    """A user cancelling an active operation receives cancellation confirmation and clear_pending=True."""
    pipeline = MagicMock()
    qa = MagicMock()

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
    )

    now = datetime.now(timezone.utc)
    pending_op = {
        "operation_id": "op_test_1",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_MAIN",
        "thread_ts": "100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": (now + timedelta(minutes=15)).isoformat(),
    }
    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="100.1",
        user_id="U_ALICE",
        pending_operation=pending_op,
    )
    q = Question(text="Never mind, cancel it", context=ctx, target_user_id="U_ALICE")

    ans = engine.ask(q)

    assert "cancelled" in ans.text.lower()
    assert ans.clear_pending is True


def test_simple_cognitive_engine_pending_operation_continuation():
    """Providing missing details executes the action via CalendarAgent and clears pending state."""
    pipeline = MagicMock()
    qa = MagicMock()
    calendar_agent = MagicMock()
    calendar_agent.handle_message.return_value = "Done! I've added Architecture Sync to the calendar."

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
    )

    now = datetime.now(timezone.utc)
    pending_op = {
        "operation_id": "op_test_2",
        "intent": "calendar_action",
        "target_agent": "calendar_agent",
        "action": "create_event",
        "collected_entities": {"title": "Architecture Sync"},
        "missing_fields": ["date", "time"],
        "user_id": "U_ALICE",
        "channel_id": "C_MAIN",
        "thread_ts": "100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": (now + timedelta(minutes=15)).isoformat(),
    }
    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="100.1",
        user_id="U_ALICE",
        pending_operation=pending_op,
    )

    q = Question(text="Tomorrow at 3pm", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert calendar_agent.handle_message.called
    assert "Done! I've added" in ans.text
    assert ans.clear_pending is True


def test_simple_cognitive_engine_selective_specialist_dispatch():
    """An operations question queries only operations agent and not unrelated specialists."""
    pipeline = MagicMock()
    qa = MagicMock()
    qa.retrieve_evidence.return_value = []
    qa.answer_from_evidence.return_value = Answer(text="Here are the decisions.", confidence=1.0)

    operations_agent = MagicMock()
    operations_agent.retrieve_evidence.return_value = ["Decision: Migrated to PostgreSQL"]

    governance_agent = MagicMock()
    calendar_agent = MagicMock()
    knowledge_agent = MagicMock()

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        governance_agent=governance_agent,
        calendar_agent=calendar_agent,
        knowledge_agent=knowledge_agent,
    )

    q = Question(text="What decisions were made about PostgreSQL?")
    ans = engine.ask(q)

    assert operations_agent.retrieve_evidence.called
    governance_agent.retrieve_evidence.assert_not_called()
    calendar_agent.retrieve_evidence.assert_not_called()
    knowledge_agent.retrieve_evidence.assert_not_called()
    assert ans.text == "Here are the decisions."


def test_api_employee_slack_user_id_not_confused_with_requester():
    """API requests providing employee_slack_user_id (target_user_id) without context do not establish requester ownership."""
    pipeline = MagicMock()
    qa = MagicMock()

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
    )

    # Stateless API call with employee_slack_user_id (context is None)
    q = Question(
        text="Schedule a sync with Bob",
        target_user_id="U_BOB",
        context=None,
    )

    ans = engine.ask(q)

    # Needs clarification, but since context is None, no pending operation is stored for U_BOB
    assert "date and time" in ans.text.lower()
    assert ans.pending_operation is None


def test_bootstrap_cognitive_planner_wiring():
    """Verify production bootstrap wires CognitivePlanner with shared llm_client into SimpleCognitiveEngine."""
    from application.bootstrap.bootstrap import bootstrap
    from domain.calendar.repositories import CalendarRepository

    with patch("application.bootstrap.bootstrap.PostgreSQLCalendarRepository") as mock_repo_cls, \
         patch("application.bootstrap.bootstrap.PostgreSQLGovernanceRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLCommunicationRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLActivityRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingTranscriptRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLTeamsSubscriptionRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLReminderRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOperationalItemRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOrganizationEventRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseDocumentRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseChunkRepository"), \
         patch("application.bootstrap.bootstrap.MinIOKnowledgeBaseStorage"), \
         patch("application.bootstrap.bootstrap.SlackClient") as mock_slack_cls, \
         patch("application.bootstrap.bootstrap.SlackIdentityService") as mock_identity_cls, \
         patch("application.bootstrap.bootstrap.MicrosoftGraphTokenProvider"), \
         patch("application.bootstrap.bootstrap.OpenRouterClient") as mock_openrouter_cls:

        mock_openrouter = MagicMock()
        mock_openrouter_cls.return_value = mock_openrouter

        mock_repo = MagicMock(spec=CalendarRepository)
        mock_repo_cls.return_value = mock_repo
        mock_slack_cls.return_value = MagicMock()
        mock_identity_cls.return_value = MagicMock()

        container = bootstrap()

        assert container.engine.planner is not None
        assert isinstance(container.engine.planner, CognitivePlanner)
        assert container.engine.planner._llm_client is mock_openrouter
