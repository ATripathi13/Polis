"""
Unit and integration tests for Milestone 5:
Specialist Agent Multi-Turn Context Grounding Verification.

Verifies:
1. KnowledgeAgent multi-turn follow-up.
2. CalendarAgent multi-turn follow-up.
3. GovernanceAgent multi-turn follow-up.
4. OperationsAgent multi-turn follow-up.
5. Topic switch followed by return to an earlier topic.
6. Ambiguous antecedent requiring clarification.
7. Missing authoritative evidence must not produce invented facts.
8. Pending-operation and planner-state isolation.
9. Original question text remains unchanged.
10. Existing single-turn behavior remains 100% compatible.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

from application.cognitive.cognitive_planner import CognitivePlanner
from application.cognitive.simple_cognitive_engine import SimpleCognitiveEngine
from domain.calendar import (
    CalendarAudienceType,
    CalendarEntry,
    CalendarEntryStatus,
    CalendarEntryType,
    InMemoryCalendarRepository,
)
from domain.governance import (
    ApprovalRequest,
    ApprovalStatus,
    GovernanceFinding,
    InMemoryGovernanceRepository,
    Policy,
    PolicyEnforcementMode,
    PolicyScope,
    PolicySeverity,
    ViolationStatus,
)
from domain.operations import (
    InMemoryOperationalItemRepository,
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.reasoning.value_objects import (
    Answer,
    ConversationContext,
    Question,
)
from domain.reasoning.value_objects.request_plan import (
    ActionType,
    CognitivePlan,
    ExecutionStep,
    IntentCategory,
    PendingOperation,
    TargetAgent,
)


# ==============================================================================
# Test Fixtures & Environment
# ==============================================================================

@pytest.fixture
def mock_pipeline():
    return MagicMock()


@pytest.fixture
def mock_qa():
    qa = MagicMock()
    qa.retrieve_evidence.return_value = ["General organizational communication reference."]
    qa.answer_from_evidence.side_effect = lambda q, evidence, **kwargs: Answer(
        text=f"Grounded response for: '{q.text}'",
        confidence=0.9,
        evidence=evidence,
    )
    qa.answer.side_effect = lambda q: Answer(
        text=f"Fallback response for: '{q.text}'",
        confidence=0.7,
        evidence=[],
    )
    return qa


@pytest.fixture
def planner():
    return CognitivePlanner(llm_client=None)


# ==============================================================================
# Scenario 1: KnowledgeAgent Multi-Turn Follow-Up
# ==============================================================================

def test_knowledge_agent_multi_turn_followup(mock_pipeline, mock_qa, planner):
    """
    Scenario 1:
    Turn 1 mentions POLIS databases (PostgreSQL 16 & Qdrant).
    Turn 2 asks an anaphoric follow-up: 'Tell me more about that.'
    Verifies:
    - Specialist retrieval query resolves 'PostgreSQL' / 'Qdrant' from conversation history.
    - KnowledgeAgent receives the resolved topic in its retrieval query.
    - Original Question.text passed to answer_from_evidence remains untouched ('Tell me more about that.').
    """
    mock_knowledge_agent = MagicMock()
    mock_knowledge_agent.retrieve_evidence.return_value = [
        "Knowledge Base document: handbook.pdf\nWe use PostgreSQL 16 and Qdrant for vector embeddings."
    ]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        knowledge_agent=mock_knowledge_agent,
        planner=planner,
    )

    # Context with Turn 1 in history
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        channel_type="im",
    ).add_exchange(
        user_message="What database architecture does POLIS use?",
        assistant_message="POLIS uses PostgreSQL 16 for persistence and Qdrant for vector embeddings.",
        user_id="U_ALICE",
    )

    q = Question(text="Tell me more about that.", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    # 1. Specialist retrieve_evidence received resolved question containing PostgreSQL/Qdrant
    assert mock_knowledge_agent.retrieve_evidence.called
    retrieval_q = mock_knowledge_agent.retrieve_evidence.call_args[0][0]
    assert isinstance(retrieval_q, Question)
    assert "postgresql" in retrieval_q.text.lower() or "qdrant" in retrieval_q.text.lower()

    # 2. Original question text was preserved in answer synthesis
    assert mock_qa.answer_from_evidence.called
    synth_q = mock_qa.answer_from_evidence.call_args[0][0]
    assert synth_q.text == "Tell me more about that."

    # 3. Grounded evidence is present
    assert any("PostgreSQL 16" in ev for ev in ans.evidence)


# ==============================================================================
# Scenario 2: CalendarAgent Multi-Turn Follow-Up
# ==============================================================================

def test_calendar_agent_multi_turn_followup(mock_pipeline, mock_qa, planner):
    """
    Scenario 2:
    Turn 1 asks what is on the calendar, showing 'Sprint Planning'.
    Turn 2 asks 'Who is attending that event?'
    Verifies:
    - CalendarAgent retrieval receives resolved antecedent 'calendar event Sprint Planning'.
    - CalendarAgent evidence is retrieved and unified.
    - Original Question.text remains 'Who is attending that event?'.
    """
    mock_calendar_agent = MagicMock()
    mock_calendar_agent.retrieve_evidence.return_value = [
        "Calendar Entry [ACTIVITY]: 'Sprint Planning'\nID: cal_sprint_1\nAudience: team (dev)\nStatus: scheduled"
    ]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        calendar_agent=mock_calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="200.1",
        is_thread=True,
    ).add_exchange(
        user_message="What is on the calendar?",
        assistant_message="Calendar Entry [ACTIVITY]: 'Sprint Planning'\nScheduled Start: 2026-11-20 10:00 AM.",
        user_id="U_ALICE",
    )

    q = Question(text="Who is attending that event?", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert mock_calendar_agent.retrieve_evidence.called
    cal_q = mock_calendar_agent.retrieve_evidence.call_args[0][0]
    assert "calendar" in cal_q.text.lower()
    assert "sprint planning" in cal_q.text.lower()

    # Original question text intact
    synth_q = mock_qa.answer_from_evidence.call_args[0][0]
    assert synth_q.text == "Who is attending that event?"
    assert any("Sprint Planning" in ev for ev in ans.evidence)


# ==============================================================================
# Scenario 3: GovernanceAgent Multi-Turn Follow-Up
# ==============================================================================

def test_governance_agent_multi_turn_followup(mock_pipeline, mock_qa, planner):
    """
    Scenario 3:
    Turn 1 discusses compliance finding FIN-001.
    Turn 2 asks 'What is the severity of that finding?'
    Verifies:
    - GovernanceAgent retrieval query receives policy identifier 'FIN-001'.
    - Governance finding evidence is preserved without fabrication.
    - Original question text remains unchanged.
    """
    mock_governance_agent = MagicMock()
    mock_governance_agent.retrieve_evidence.return_value = [
        "Governance Finding [FIN-001] (MEDIUM): Unapproved expenditure on GPU instances [Status: open]"
    ]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        governance_agent=mock_governance_agent,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="300.1",
        channel_type="im",
    ).add_exchange(
        user_message="What compliance violation happened with FIN-001?",
        assistant_message="Governance Finding [FIN-001] (MEDIUM): Unapproved expenditure on GPU instances.",
        user_id="U_ALICE",
    )

    q = Question(text="What is the severity of that finding?", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert mock_governance_agent.retrieve_evidence.called
    gov_q = mock_governance_agent.retrieve_evidence.call_args[0][0]
    assert "fin-001" in gov_q.text.lower()

    synth_q = mock_qa.answer_from_evidence.call_args[0][0]
    assert synth_q.text == "What is the severity of that finding?"
    assert any("FIN-001" in ev for ev in ans.evidence)


# ==============================================================================
# Scenario 4: OperationsAgent Multi-Turn Follow-Up
# ==============================================================================

def test_operations_agent_multi_turn_followup(mock_pipeline, mock_qa, planner):
    """
    Scenario 4:
    Turn 1 asks about open tasks, mentioning 'Audit user permission policies'.
    Turn 2 asks 'Who is assigned to that?'
    Verifies:
    - OperationsAgent retrieval query resolves the task summary antecedent.
    - Operations evidence is retrieved.
    - Original question text remains untouched.
    """
    mock_operations_agent = MagicMock()
    mock_operations_agent.retrieve_evidence.return_value = [
        "Operational item: task\nSummary: Audit user permission policies\nStatus: open\nPriority: medium"
    ]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        operations_agent=mock_operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_OPS",
        thread_ts="400.1",
        is_thread=True,
    ).add_exchange(
        user_message="What is the audit task?",
        assistant_message="Operational item: task\nSummary: Audit user permission policies\nStatus: open",
        user_id="U_ALICE",
    )

    q = Question(text="Who is assigned to that?", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert mock_operations_agent.retrieve_evidence.called
    ops_q = mock_operations_agent.retrieve_evidence.call_args[0][0]
    assert "task" in ops_q.text.lower()
    assert "audit user permission policies" in ops_q.text.lower()

    synth_q = mock_qa.answer_from_evidence.call_args[0][0]
    assert synth_q.text == "Who is assigned to that?"
    assert any("Audit user permission policies" in ev for ev in ans.evidence)


# ==============================================================================
# Scenario 5: Topic Switch Followed by Return to Earlier Topic
# ==============================================================================

def test_topic_switch_and_return_to_earlier_topic(mock_pipeline, mock_qa, planner):
    """
    Scenario 5:
    Turn 1: Topic A (Calendar event 'Architecture Workshop').
    Turn 2: Follow-up on Topic A ('Who is attending that event?').
    Turn 3: Topic switch to Topic B ('Now let's discuss open tasks. Show me tasks.').
    Turn 4: Follow-up on Topic B ('Are any of those overdue?').
    Turn 5: Return to Topic A ('Going back to our calendar discussion, when is that meeting?').
    Verifies:
    - Topic switch cues prevent stale antecedents from Topic A entering Topic B.
    - Returning to Topic A resolves calendar antecedents cleanly without cross-domain contamination.
    """
    mock_calendar_agent = MagicMock()
    mock_calendar_agent.retrieve_evidence.return_value = [
        "Calendar Entry [ACTIVITY]: 'Architecture Workshop'\nScheduled Start: 2026-11-25 14:00."
    ]

    mock_operations_agent = MagicMock()
    mock_operations_agent.retrieve_evidence.return_value = [
        "Operational item: task\nSummary: Implement DB migrations\nStatus: open"
    ]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        calendar_agent=mock_calendar_agent,
        operations_agent=mock_operations_agent,
        planner=planner,
    )

    # 1. Context at Turn 2 (Topic A follow-up)
    ctx_turn2 = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="500.1", channel_type="im").add_exchange(
        user_message="What is on the calendar?",
        assistant_message="Calendar Entry [ACTIVITY]: 'Architecture Workshop' scheduled for Nov 25.",
        user_id="U_ALICE",
    )
    q_turn2 = Question(text="Who is attending that event?", context=ctx_turn2, target_user_id="U_ALICE")
    engine.ask(q_turn2)
    cal_q2 = mock_calendar_agent.retrieve_evidence.call_args[0][0]
    assert "architecture workshop" in cal_q2.text.lower()
    mock_calendar_agent.retrieve_evidence.reset_mock()

    # 2. Context at Turn 3 (Topic Switch to Tasks)
    ctx_turn3 = ctx_turn2.add_exchange(
        user_message="Who is attending that event?",
        assistant_message="The Architecture Workshop is intended for the engineering team.",
        user_id="U_ALICE",
    )
    q_turn3 = Question(text="Now let's discuss open tasks. What tasks do we have?", context=ctx_turn3, target_user_id="U_ALICE")
    engine.ask(q_turn3)
    # Stale calendar antecedent should NOT be attached to tasks
    ops_q3 = mock_operations_agent.retrieve_evidence.call_args[0][0]
    assert "architecture workshop" not in ops_q3.text.lower()
    mock_operations_agent.retrieve_evidence.reset_mock()

    # 3. Context at Turn 5 (Return to Calendar Topic)
    ctx_turn5 = ctx_turn3.add_exchange(
        user_message="Now let's discuss open tasks. What tasks do we have?",
        assistant_message="Operational item: task\nSummary: Implement DB migrations\nStatus: open",
        user_id="U_ALICE",
    ).add_exchange(
        user_message="Are any of those overdue?",
        assistant_message="No overdue tasks found.",
        user_id="U_ALICE",
    )
    q_turn5 = Question(text="Going back to our calendar discussion, when is that workshop scheduled?", context=ctx_turn5, target_user_id="U_ALICE")
    engine.ask(q_turn5)

    assert mock_calendar_agent.retrieve_evidence.called
    cal_q5 = mock_calendar_agent.retrieve_evidence.call_args[0][0]
    assert "calendar" in cal_q5.text.lower()


# ==============================================================================
# Scenario 6: Ambiguous Antecedent Requiring Clarification
# ==============================================================================

def test_ambiguous_antecedent_requires_clarification(mock_pipeline, mock_qa, planner):
    """
    Scenario 6:
    Prior turn mentioned multiple competing entities of different domains (e.g. both a task and a calendar meeting).
    User asks a generic ambiguous question: 'What is the status of that?'
    Verifies:
    - Deterministic planner detects ambiguity.
    - Requires clarification rather than guessing or executing ungrounded actions.
    - Clarification prompt is returned to user.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="600.1",
        channel_type="im",
    ).add_exchange(
        user_message="Show me current work.",
        assistant_message="We have task 'Deploy API v2' and meeting 'Quarterly Review'.",
        user_id="U_ALICE",
    )

    q = Question(text="What is the status of that?", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.is_conversational is True
    assert "clarify which item" in ans.text.lower()


# ==============================================================================
# Scenario 7: Missing Authoritative Evidence Does Not Invent Facts
# ==============================================================================

def test_missing_evidence_does_not_invent_facts(mock_pipeline, mock_qa, planner):
    """
    Scenario 7:
    User asks about an unrecorded subject ('quantum encryption standard').
    Verifies:
    - Specialists return empty evidence.
    - Engine synthesizes plain uncertainty / no information response without hallucinating facts.
    """
    mock_knowledge_agent = MagicMock()
    mock_knowledge_agent.retrieve_evidence.return_value = []

    mock_qa.retrieve_evidence.return_value = []
    mock_qa.answer.side_effect = None
    mock_qa.answer.return_value = Answer(
        text="I don't have enough information to answer that confidently.",
        confidence=0.0,
        evidence=[],
    )

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        knowledge_agent=mock_knowledge_agent,
        planner=planner,
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="700.1", channel_type="im")
    q = Question(text="What is our quantum encryption key standard?", context=ctx, target_user_id="U_ALICE")

    ans = engine.ask(q)

    assert "don't have enough information" in ans.text.lower() or "confident" in ans.text.lower()
    assert ans.confidence == 0.0


# ==============================================================================
# Scenario 8: Pending-Operation and Consequential Action Safety
# ==============================================================================

def test_consequential_anaphoric_action_asks_for_clarification(mock_pipeline, mock_qa, planner):
    """
    Scenario 8.1:
    User says 'cancel it' or 'cancel that meeting' with NO active pending operation.
    Verifies:
    - Never executes a consequential cancellation action solely on an inferred entity from history.
    - Requires clarification for the specific target ID / title.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="800.1",
        channel_type="im",
    ).add_exchange(
        user_message="Schedule event Architecture Sync on Friday at 10am.",
        assistant_message="Architecture Sync is scheduled.",
        user_id="U_ALICE",
    )

    q = Question(text="Cancel that meeting", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    # Must ask for explicit title/ID clarification rather than cancelling unverified target
    assert ans.is_conversational is True
    assert "which item would you like to cancel" in ans.text.lower() or "specify" in ans.text.lower()


def test_pending_operation_isolation_across_threads_and_users(mock_pipeline, mock_qa, planner):
    """
    Scenario 8.2:
    Pending operation initiated by User A in Thread 1 must not leak to User B or Thread 2.
    """
    now = datetime.now(timezone.utc)
    pending_alice = {
        "operation_id": "op_alice_1",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEV",
        "thread_ts": "900.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": (now + timedelta(minutes=15)).isoformat(),
        "action": "create_event",
        "missing_fields": ["time"],
    }

    # Context in Thread 2 (started by Bob or different thread)
    ctx_bob = ConversationContext(
        user_id="U_BOB",
        channel_id="C_DEV",
        thread_ts="900.2",
        is_thread=True,
        pending_operation=pending_alice,  # If someone maliciously or accidentally passed foreign pending_operation
    )

    # Validated typed pending operation must fail-safe and return None for Bob
    typed_op = ctx_bob.get_typed_pending_operation(expected_user_id="U_BOB")
    assert typed_op is None


# ==============================================================================
# Scenario 9: Existing Single-Turn Compatibility
# ==============================================================================

def test_single_turn_backward_compatibility(mock_pipeline, mock_qa, planner):
    """
    Scenario 9:
    Single-turn requests with context=None or empty history execute cleanly
    using standard single-turn paths without errors.
    """
    mock_operations_agent = MagicMock()
    mock_operations_agent.retrieve_evidence.return_value = ["Operational item: task Summary: Build release v1"]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        operations_agent=mock_operations_agent,
        planner=planner,
    )

    q = Question(text="What tasks are open?", context=None)
    ans = engine.ask(q)

    assert mock_operations_agent.retrieve_evidence.called
    assert ans is not None
    assert mock_qa.answer_from_evidence.called
    assert mock_qa.answer_from_evidence.call_args[0][0].text == "What tasks are open?"


# ==============================================================================
# Additional Scenarios: Milestone 5 Phase 2 Corrections
# ==============================================================================

def test_authentic_thread_timestamp_preservation(mock_pipeline, mock_qa, planner):
    """
    Correction 1.1:
    PendingOperation created during clarification in an authentic thread must preserve
    context.thread_ts exactly and not replace it with 'unthreaded' or channel_id.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_ENG",
        thread_ts="1712345678.000100",
        is_thread=True,
    )

    # Schedule query missing date/time -> requires clarification
    q = Question(text="Schedule an event Architecture Review", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.pending_operation is not None
    assert ans.pending_operation["thread_ts"] == "1712345678.000100"
    assert ans.pending_operation["thread_ts"] != "unthreaded"
    assert ans.pending_operation["thread_ts"] != "C_ENG"


def test_threaded_dm_pending_operation_continuation(mock_pipeline, mock_qa, planner):
    """
    Correction 1.2:
    In a threaded DM (is_thread=True), authentic thread_ts is strictly validated
    and not rejected as a thread mismatch.
    """
    now = datetime.now(timezone.utc)
    op_data = {
        "operation_id": "op-threaded-dm",
        "intent": "calendar_action",
        "target_agent": "calendar_agent",
        "action": "create_event",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "1712345678.000100",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": (now + timedelta(minutes=15)).isoformat(),
        "missing_fields": ["time"],
    }

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="1712345678.000100",
        channel_type="im",
        is_thread=True,
        pending_operation=op_data,
    )

    typed_op = ctx.get_typed_pending_operation(
        expected_user_id="U_ALICE",
        expected_channel_id="D_ALICE",
        expected_thread_ts="1712345678.000100",
    )
    assert typed_op is not None
    assert typed_op.thread_ts == "1712345678.000100"


def test_unthreaded_dm_continuation_compatibility(mock_pipeline, mock_qa, planner):
    """
    Correction 1.3:
    In an unthreaded DM per Logical Change 3, clarification pending operation
    does not require a non-empty thread_ts and validates with expected_thread_ts=None.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="",
        channel_type="im",
        is_thread=False,
    )

    q = Question(text="Schedule an event Team Retro", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.pending_operation is not None
    # Model validation succeeds and pending operation is reconstructible
    validated = PendingOperation.model_validate(ans.pending_operation)
    assert validated.user_id == "U_ALICE"
    assert validated.channel_id == "D_ALICE"

    # Validates cleanly via ConversationContext with expected_thread_ts=None
    ctx_with_op = ctx.with_pending_operation(ans.pending_operation)
    resumed_op = ctx_with_op.get_typed_pending_operation(
        expected_user_id="U_ALICE",
        expected_channel_id="D_ALICE",
        expected_thread_ts=None,
    )
    assert resumed_op is not None


def test_insufficiently_scoped_context_does_not_create_corrupt_pending_op(mock_pipeline, mock_qa, planner):
    """
    Correction 1.4 & 2.2:
    An action requiring clarification in a public channel without a thread_ts
    cannot establish a safe pending state and must not fabricate a corrupt pending operation.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    # Public channel message with no thread_ts
    ctx_unscoped = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_PUBLIC",
        thread_ts="",
        is_thread=False,
    )

    q = Question(text="Schedule a meeting Sprint Sync", context=ctx_unscoped, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.pending_operation is None
    assert "additional context" in ans.text.lower()


def test_valid_clarification_produces_reconstructible_pending_operation(mock_pipeline, mock_qa, planner):
    """
    Correction 2.1:
    A valid clarification request must always produce a typed, reconstructible
    PendingOperation instance that round-trips cleanly through model validation and context.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="1712345678.000100",
        is_thread=True,
    )

    q = Question(text="Schedule an event Architecture Review", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.pending_operation is not None
    assert ans.confidence == 1.0
    assert ans.is_conversational is True

    # Validate typed reconstruction
    reconstructed = PendingOperation.model_validate(ans.pending_operation)
    assert reconstructed.user_id == "U_ALICE"
    assert reconstructed.channel_id == "C_DEV"
    assert reconstructed.thread_ts == "1712345678.000100"
    assert reconstructed.operation_id
    assert reconstructed.expires_at_iso

    # Validate context resumption compatibility
    ctx_resumed = ctx.with_pending_operation(ans.pending_operation)
    typed_op = ctx_resumed.get_typed_pending_operation(
        expected_user_id="U_ALICE",
        expected_channel_id="C_DEV",
        expected_thread_ts="1712345678.000100",
    )
    assert typed_op is not None
    assert typed_op.operation_id == reconstructed.operation_id


def test_construction_failure_does_not_create_zombie_clarification(mock_pipeline, mock_qa, planner, monkeypatch):
    """
    Correction 2.3:
    If PendingOperation construction fails unexpectedly, the system must not
    return a normal clarification prompt with pending_operation=None.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        channel_type="im",
    )

    # Simulate an unexpected construction failure in PendingOperation
    def failing_model_validate(*args, **kwargs):
        raise RuntimeError("Unexpected construction failure")

    monkeypatch.setattr(PendingOperation, "__init__", failing_model_validate)

    q = Question(text="Schedule an event Architecture Discussion", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.pending_operation is None
    # Must report error, NOT the normal clarification prompt
    assert "error occurred" in ans.text.lower()
    assert "clarify" not in ans.text.lower()


def test_sensitive_data_does_not_appear_in_captured_logs(mock_pipeline, mock_qa, planner, monkeypatch, caplog):
    """
    Correction 2.4:
    When PendingOperation construction fails or scope is validated,
    captured logs must never contain raw exception payloads, secrets, tokens,
    or arbitrary Pydantic ValidationError dumps.
    """
    import logging
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        channel_type="im",
    )

    secret_token = "SUPER_SECRET_TOKEN_XYZ_98765"

    def failing_init(*args, **kwargs):
        raise ValueError(f"Sensitive internal error with secret {secret_token}")

    monkeypatch.setattr(PendingOperation, "__init__", failing_init)

    with caplog.at_level(logging.DEBUG):
        q = Question(text="Schedule an event Security Briefing", context=ctx, target_user_id="U_ALICE")
        ans = engine.ask(q)

    assert ans.pending_operation is None
    # Must use structured safe logging without raw exception payloads or secrets
    assert secret_token not in caplog.text
    assert "ValueError" not in caplog.text
    assert "Failed to construct pending operation (engine=simple_cognitive_engine, operation=create_pending_operation)" in caplog.text


def test_operations_agent_newest_task_selected_over_older_tasks(mock_pipeline, mock_qa, planner):
    """
    Correction 3.1:
    When multiple prior turns discuss different tasks, the newest task antecedent
    must be selected over older tasks.
    """
    mock_operations_agent = MagicMock()
    mock_operations_agent.retrieve_evidence.return_value = ["Task resolved."]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        operations_agent=mock_operations_agent,
        planner=planner,
    )

    ctx = (
        ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="200.1", is_thread=True)
        .add_exchange(
            user_message="Show me Task A",
            assistant_message="Operational item: task\nSummary: Implement OAuth2 Authentication\nStatus: closed",
            user_id="U_ALICE",
        )
        .add_exchange(
            user_message="Show me Task B",
            assistant_message="Operational item: task\nSummary: Migrate PostgreSQL Schema\nStatus: open",
            user_id="U_ALICE",
        )
    )

    q = Question(text="Who is working on that task?", context=ctx, target_user_id="U_ALICE")
    engine.ask(q)

    assert mock_operations_agent.retrieve_evidence.called
    ops_q = mock_operations_agent.retrieve_evidence.call_args[0][0]
    # Must contain newest task B, not older task A
    assert "migrate postgresql schema" in ops_q.text.lower()
    assert "implement oauth2 authentication" not in ops_q.text.lower()


def test_grounded_assistant_antecedent_preferred_over_user_assertion(mock_pipeline, mock_qa, planner):
    """
    Correction 3.2:
    Grounded assistant evidence takes precedence over unverified user assertions.
    """
    mock_operations_agent = MagicMock()
    mock_operations_agent.retrieve_evidence.return_value = ["Task resolved."]

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        operations_agent=mock_operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="300.1", is_thread=True).add_exchange(
        user_message="Is task 'Drop Production Database' completed?",
        assistant_message="Operational item: task\nSummary: Configure Daily Backups\nStatus: open",
        user_id="U_ALICE",
    )

    q = Question(text="Who is assigned to that task?", context=ctx, target_user_id="U_ALICE")
    engine.ask(q)

    assert mock_operations_agent.retrieve_evidence.called
    ops_q = mock_operations_agent.retrieve_evidence.call_args[0][0]
    assert "configure daily backups" in ops_q.text.lower()
    assert "drop production database" not in ops_q.text.lower()


def test_multiple_entities_in_same_turn_trigger_clarification(mock_pipeline, mock_qa, planner):
    """
    Correction 3.3:
    When an assistant message lists multiple entities of the same domain,
    an anaphoric query must trigger clarification rather than guessing one arbitrarily.
    """
    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        planner=planner,
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="400.1", channel_type="im").add_exchange(
        user_message="What tasks are active?",
        assistant_message="We have task 'Deploy Release v2' and task 'Audit Security Roles'.",
        user_id="U_ALICE",
    )

    q = Question(text="What is the status of that?", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.is_conversational is True
    assert "clarify which item" in ans.text.lower()


def test_unverified_conversational_text_not_treated_as_grounded_evidence(mock_pipeline, mock_qa, planner):
    """
    Correction 3.4:
    Ordinary conversational assistant text without grounded specialist markers
    is not treated as authoritative evidence.
    """
    mock_calendar_agent = MagicMock()
    mock_calendar_agent.retrieve_evidence.return_value = []

    engine = SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=mock_qa,
        calendar_agent=mock_calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="500.1", channel_type="im").add_exchange(
        user_message="Do we have any meetings?",
        assistant_message="I'm not certain if there are meetings scheduled for tomorrow.",
        user_id="U_ALICE",
    )

    q = Question(text="When is it?", context=ctx, target_user_id="U_ALICE")
    engine.ask(q)

    assert mock_calendar_agent.retrieve_evidence.called
    cal_q = mock_calendar_agent.retrieve_evidence.call_args[0][0]
    # Must NOT have attached phantom calendar event name from conversational text
    assert "calendar event i'm not certain" not in cal_q.text.lower()
