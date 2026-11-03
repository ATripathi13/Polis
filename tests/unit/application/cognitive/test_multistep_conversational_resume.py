"""
Unit and integration tests for Stage B5.4: Conversational Resume & Multi-Step State Persistence.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from application.cognitive import SimpleCognitiveEngine
from domain.governance.enums import ApprovalStatus
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
    OperationsResult,
)
from domain.organization import OrganizationEventType
from domain.reasoning.value_objects.answer import Answer
from domain.reasoning.value_objects.conversation_context import ConversationContext
from domain.reasoning.value_objects.question import Question
from domain.reasoning.value_objects.request_plan import (
    ActionType,
    CognitivePlan,
    ExecutionStep,
    ExtractedEntities,
    IntentCategory,
    PendingOperation,
    TargetAgent,
)
from domain.reasoning.value_objects.step_execution import (
    MultiStepExecutionResult,
    MultiStepExecutionStatus,
    StepExecutionResult,
    StepExecutionStatus,
)
from infrastructure.database.conversation_repository import InMemoryConversationRepository


def _make_engine(
    operations_agent=None,
    calendar_agent=None,
    governance_agent=None,
    planner=None,
    coordinator=None,
):
    pipeline = MagicMock()
    qa = MagicMock()
    return SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
        governance_agent=governance_agent,
        planner=planner,
        coordinator=coordinator,
    )


# =========================================================================
# 1. A plan paused for clarification is persisted
# =========================================================================

def test_plan_paused_for_clarification_is_persisted():
    operations_agent = MagicMock()
    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Create cluster",
        status=OperationalItemStatus.OPEN,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_101",
    )

    # Step 1 succeeds; Step 2 lacks summary so specialist returns clarification
    step1 = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Create cluster"},
    )
    step2 = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        dependencies=["step_1"],
        parameters={},  # Missing summary!
    )
    plan = CognitivePlan(
        request_id="plan_pause_1",
        original_message="Create cluster and subtask",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1")
    q = Question(text="Create cluster and subtask", context=ctx)
    ans = engine.ask(q)

    assert not ans.clear_pending
    assert ans.pending_operation is not None
    pending_dict = ans.pending_operation
    assert pending_dict["plan_id"] == "plan_pause_1"
    assert pending_dict["pending_step_id"] == "step_2"
    assert "step_1" in pending_dict["completed_step_results"]
    assert pending_dict["completed_step_results"]["step_1"]["status"] == "succeeded"


# =========================================================================
# 2. Persisted execution state can be reconstructed
# =========================================================================

def test_persisted_execution_state_reconstruction():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)

    step1 = ExecutionStep(step_id="step_1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task")
    step2 = ExecutionStep(step_id="step_2", agent=TargetAgent.CALENDAR_AGENT, action="create_event", dependencies=["step_1"])
    plan = CognitivePlan(
        request_id="plan_recon",
        original_message="Create task and meeting",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        execution_steps=[step1, step2],
    )

    pending = PendingOperation(
        operation_id="op_recon",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        collected_entities={"event_title": "Sprint Review"},
        missing_fields=["start_time"],
        clarification_question="What time is the review?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
        state_version=1,
        plan_id="plan_recon",
        original_plan=plan.model_dump(),
        step_states={"step_1": "succeeded", "step_2": "pending"},
        completed_step_results={
            "step_1": {
                "step_id": "step_1",
                "agent": "operations_agent",
                "action": "create_task",
                "status": "succeeded",
                "entity_id": "TASK-555",
                "output_fields": {"task_id": "TASK-555", "entity_id": "TASK-555"},
                "answer": "Task created.",
            }
        },
        pending_step_id="step_2",
    )

    dumped = pending.model_dump()
    reconstructed = PendingOperation.model_validate(dumped)

    assert reconstructed.is_multi_step
    orig_plan = reconstructed.get_original_plan()
    assert orig_plan is not None
    assert orig_plan.request_id == "plan_recon"
    assert len(orig_plan.execution_steps) == 2

    completed = reconstructed.get_completed_results()
    assert "step_1" in completed
    assert completed["step_1"].status == StepExecutionStatus.SUCCEEDED
    assert completed["step_1"].entity_id == "TASK-555"
    assert completed["step_1"].get_output("task_id") == "TASK-555"
    assert completed["step_1"].domain_result is None


# =========================================================================
# 3. Original plan ID and step IDs remain stable after continuation
# =========================================================================

def test_original_plan_and_step_ids_remain_stable_after_continuation():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)

    step1 = ExecutionStep(step_id="step_1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "Task 1"})
    step2 = ExecutionStep(step_id="step_2", agent=TargetAgent.CALENDAR_AGENT, action="create_event", dependencies=["step_1"], parameters={"title": "Planning"})
    orig_plan = CognitivePlan(
        request_id="plan_stable_999",
        original_message="Create task and meeting",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )

    pending = PendingOperation(
        operation_id="op_stable",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        missing_fields=["time"],
        clarification_question="What time is the meeting?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
        plan_id="plan_stable_999",
        original_plan=orig_plan.model_dump(),
        completed_step_results={"step_1": {"step_id": "step_1", "agent": "operations_agent", "action": "create_task", "status": "succeeded", "entity_id": "T1"}},
        pending_step_id="step_2",
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        pending_operation=pending.model_dump(),
    )

    from application.cognitive import CognitivePlanner
    planner = CognitivePlanner()
    resumed_plan = planner.plan(Question(text="At 3pm", context=ctx), context=ctx)

    assert resumed_plan.request_id == "plan_stable_999"
    assert [s.step_id for s in resumed_plan.execution_steps] == ["step_1", "step_2"]
    assert resumed_plan.execution_steps[1].dependencies == ["step_1"]


# =========================================================================
# 4. Successfully completed steps are not executed again
# =========================================================================

def test_successfully_completed_steps_not_reexecuted():
    operations_agent = MagicMock()
    calendar_agent = MagicMock()

    # Step 1 was already completed in prior turn
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    step1 = ExecutionStep(step_id="step_task", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "Audit server"})
    step2 = ExecutionStep(
        step_id="step_cal",
        agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        dependencies=["step_task"],
        parameters={"title": "Audit Review", "audience_type": "organization", "audience_identifier": "all"},
    )
    orig_plan = CognitivePlan(
        request_id="plan_no_reexec",
        original_message="Create task and meeting",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )

    mock_cal = MagicMock()
    mock_cal.entry_id = "cal_entry_audit"
    mock_cal.title = "Audit Review"
    mock_cal.status.value = "scheduled"
    calendar_agent.create_entry_structured.return_value = mock_cal
    calendar_agent.format_confirmation.return_value = "Meeting scheduled."

    pending = PendingOperation(
        operation_id="op_no_reexec",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        missing_fields=["time"],
        clarification_question="What time?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
        plan_id="plan_no_reexec",
        original_plan=orig_plan.model_dump(),
        completed_step_results={
            "step_task": {
                "step_id": "step_task",
                "agent": "operations_agent",
                "action": "create_task",
                "status": "succeeded",
                "entity_id": "TASK-AUDIT-99",
                "output_fields": {"task_id": "TASK-AUDIT-99", "entity_id": "TASK-AUDIT-99"},
                "answer": "Task created.",
            }
        },
        pending_step_id="step_cal",
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        pending_operation=pending.model_dump(),
    )

    from application.cognitive import CognitivePlanner
    planner = CognitivePlanner()

    engine = _make_engine(
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    q = Question(text="At 14:00 on 2026-11-10", context=ctx)
    ans = engine.ask(q)

    # Operations agent was NEVER invoked in this resumption turn!
    assert operations_agent.process_event.call_count == 0
    # Calendar agent was invoked once
    assert calendar_agent.create_entry_structured.call_count == 1
    assert ans.confidence == 1.0
    assert ans.clear_pending


# =========================================================================
# 5. Clarification-pending step resumes after valid input
# =========================================================================

def test_clarification_pending_step_resumes_after_valid_input():
    operations_agent = MagicMock()
    item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Write unit tests",
        status=OperationalItemStatus.OPEN,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_resumed_ok",
    )

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    step1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={})
    step2 = ExecutionStep(step_id="s2", agent=TargetAgent.KNOWLEDGE_AGENT, action="retrieve", dependencies=["s1"], parameters={})
    orig_plan = CognitivePlan(
        request_id="plan_resume_valid",
        original_message="Create task",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )

    pending = PendingOperation(
        operation_id="op_val",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        missing_fields=["summary"],
        clarification_question="What is the task summary?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
        plan_id="plan_resume_valid",
        original_plan=orig_plan.model_dump(),
        completed_step_results={},
        pending_step_id="s1",
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    from application.cognitive import CognitivePlanner
    engine = _make_engine(operations_agent=operations_agent, planner=CognitivePlanner())

    q = Question(text="Write unit tests", context=ctx)
    ans = engine.ask(q)

    assert operations_agent.process_event.call_count == 1
    assert "task_resumed_ok" in ans.text
    assert ans.clear_pending


# =========================================================================
# 6. Invalid clarification input leaves operation pending
# =========================================================================

def test_invalid_clarification_input_leaves_operation_pending():
    operations_agent = MagicMock()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    step1 = ExecutionStep(step_id="s1", agent=TargetAgent.CALENDAR_AGENT, action="create_event", parameters={"title": "Sync"})
    orig_plan = CognitivePlan(
        request_id="plan_inv_input",
        original_message="Schedule sync",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[step1, ExecutionStep(step_id="s2", agent=TargetAgent.KNOWLEDGE_AGENT, action="retrieve", dependencies=["s1"])],
    )

    pending = PendingOperation(
        operation_id="op_inv",
        intent=IntentCategory.CALENDAR_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        missing_fields=["time"],
        clarification_question="What time is the sync?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
        plan_id="plan_inv_input",
        original_plan=orig_plan.model_dump(),
        pending_step_id="s1",
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    from application.cognitive import CognitivePlanner
    engine = _make_engine(planner=CognitivePlanner())

    # User says something that contains no time
    q = Question(text="I am not sure yet", context=ctx)
    ans = engine.ask(q)

    assert not ans.clear_pending
    assert ans.pending_operation is not None
    assert ans.pending_operation["plan_id"] == "plan_inv_input"


# =========================================================================
# 7. Dependent steps execute only after prerequisite success
# =========================================================================

def test_dependent_steps_execute_only_after_prerequisite_success():
    operations_agent = MagicMock()
    calendar_agent = MagicMock()

    call_order = []

    def mock_task_event(event, **kwargs):
        call_order.append("task")
        item = OperationalItem.create(item_type=OperationalItemType.TASK, summary="Setup DB", status=OperationalItemStatus.OPEN)
        return OperationsResult(event_type=OrganizationEventType.TASK_CREATED, operation="created", item=item, status=OperationalItemStatus.OPEN, affected_item_id="DB-1")

    def mock_cal_create(params, **kwargs):
        call_order.append("calendar")
        entry = MagicMock()
        entry.entry_id = "cal_db"
        entry.title = "DB Review"
        entry.status.value = "scheduled"
        return entry

    operations_agent.process_event.side_effect = mock_task_event
    calendar_agent.create_entry_structured.side_effect = mock_cal_create
    calendar_agent.format_confirmation.return_value = "Calendar created."

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    step1 = ExecutionStep(step_id="s1_task", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "Setup DB"})
    step2 = ExecutionStep(
        step_id="s2_cal",
        agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        dependencies=["s1_task"],
        parameters={"title": "DB Review", "audience_type": "organization", "audience_identifier": "all"},
    )
    orig_plan = CognitivePlan(
        request_id="plan_dep_seq",
        original_message="Setup DB and meeting",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )

    # s1_task is already succeeded
    pending = PendingOperation(
        operation_id="op_dep_seq",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        missing_fields=["time"],
        clarification_question="What time is DB Review?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
        plan_id="plan_dep_seq",
        original_plan=orig_plan.model_dump(),
        completed_step_results={"s1_task": {"step_id": "s1_task", "agent": "operations_agent", "action": "create_task", "status": "succeeded", "entity_id": "DB-1"}},
        pending_step_id="s2_cal",
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    from application.cognitive import CognitivePlanner
    engine = _make_engine(operations_agent=operations_agent, calendar_agent=calendar_agent, planner=CognitivePlanner())

    q = Question(text="At 11:00 on 2026-11-12", context=ctx)
    ans = engine.ask(q)

    # Task was already succeeded so not re-run; calendar executed
    assert call_order == ["calendar"]
    assert ans.clear_pending


# =========================================================================
# 8. Independent branches preserve their correct execution state
# =========================================================================

def test_independent_branches_preserve_correct_execution_state():
    governance_agent = MagicMock()
    mock_appr = MagicMock()
    mock_appr.id = "appr_indep_ok"
    mock_appr.title = "Budget Approval"
    mock_appr.target_object = "infra"
    mock_appr.status = ApprovalStatus.PENDING
    mock_appr.requester_id = "U_ALICE"
    mock_appr.policy_id = None
    mock_appr.notes = None
    governance_agent.request_approval.return_value = mock_appr

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)

    # Branch 1: task (succeeded in turn 1)
    # Branch 2: governance (independent, paused for clarification in turn 1)
    step1 = ExecutionStep(step_id="b1_task", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "Deploy cluster"})
    step2 = ExecutionStep(step_id="b2_gov", agent=TargetAgent.GOVERNANCE_AGENT, action="request_approval", dependencies=[], parameters={"title": "Budget Approval"})
    orig_plan = CognitivePlan(
        request_id="plan_indep_preserve",
        original_message="Deploy cluster and budget approval",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )

    pending = PendingOperation(
        operation_id="op_indep",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        missing_fields=["target_object"],
        clarification_question="What is the target object?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
        plan_id="plan_indep_preserve",
        original_plan=orig_plan.model_dump(),
        completed_step_results={"b1_task": {"step_id": "b1_task", "agent": "operations_agent", "action": "create_task", "status": "succeeded", "entity_id": "CLUSTER-9"}},
        pending_step_id="b2_gov",
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    from application.cognitive import CognitivePlanner
    engine = _make_engine(governance_agent=governance_agent, planner=CognitivePlanner())

    q = Question(text="on infra", context=ctx)
    ans = engine.ask(q)

    assert governance_agent.request_approval.call_count == 1
    assert ans.clear_pending
    assert "appr_indep_ok" in ans.text


# =========================================================================
# 9. A different user cannot resume another user's plan
# =========================================================================

def test_different_user_cannot_resume_another_users_plan():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    pending = PendingOperation(
        operation_id="op_alice",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        user_id="U_ALICE",
        channel_id="C_SHARED",
        thread_ts="100.1",
        expires_at_iso=expires.isoformat(),
        plan_id="plan_alice",
        original_plan={"request_id": "plan_alice", "original_message": "...", "intent": "task_action", "execution_steps": []},
    )

    # Bob sends message in same channel/thread
    ctx = ConversationContext(user_id="U_BOB", channel_id="C_SHARED", thread_ts="100.1", pending_operation=pending.model_dump())
    assert ctx.get_typed_pending_operation(expected_user_id="U_BOB") is None


# =========================================================================
# 10. A different Slack channel cannot resume the plan
# =========================================================================

def test_different_slack_channel_cannot_resume_plan():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    pending = PendingOperation(
        operation_id="op_chan",
        intent=IntentCategory.TASK_ACTION,
        user_id="U_ALICE",
        channel_id="C_CHANNEL_A",
        thread_ts="100.1",
        expires_at_iso=expires.isoformat(),
        plan_id="plan_chan",
        original_plan={"request_id": "plan_chan", "original_message": "...", "intent": "task_action", "execution_steps": []},
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_CHANNEL_B", thread_ts="100.1", pending_operation=pending.model_dump())
    assert ctx.get_typed_pending_operation(expected_channel_id="C_CHANNEL_B") is None


# =========================================================================
# 11. A different Slack thread cannot resume the plan
# =========================================================================

def test_different_slack_thread_cannot_resume_plan():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    pending = PendingOperation(
        operation_id="op_th",
        intent=IntentCategory.TASK_ACTION,
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        expires_at_iso=expires.isoformat(),
        plan_id="plan_th",
        original_plan={"request_id": "plan_th", "original_message": "...", "intent": "task_action", "execution_steps": []},
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="200.2", pending_operation=pending.model_dump())
    assert ctx.get_typed_pending_operation(expected_thread_ts="200.2") is None


# =========================================================================
# 12. Expired plans cannot resume
# =========================================================================

def test_expired_plans_cannot_resume():
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=5)
    created = past - timedelta(minutes=15)
    pending = PendingOperation(
        operation_id="op_exp",
        intent=IntentCategory.TASK_ACTION,
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=created.isoformat(),
        expires_at_iso=past.isoformat(),
        plan_id="plan_exp",
        original_plan={"request_id": "plan_exp", "original_message": "...", "intent": "task_action", "execution_steps": []},
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    assert ctx.get_typed_pending_operation() is None


# =========================================================================
# 13. Explicit cancellation prevents remaining steps from executing
# =========================================================================

def test_explicit_cancellation_prevents_remaining_steps_executing():
    operations_agent = MagicMock()
    calendar_agent = MagicMock()

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    step1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task")
    step2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="create_event", dependencies=["s1"])
    plan = CognitivePlan(request_id="p_cancel", original_message="Task and event", intent=IntentCategory.TASK_ACTION, execution_steps=[step1, step2])

    pending = PendingOperation(
        operation_id="op_canc",
        intent=IntentCategory.TASK_ACTION,
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        expires_at_iso=expires.isoformat(),
        plan_id="p_cancel",
        original_plan=plan.model_dump(),
        completed_step_results={"s1": {"step_id": "s1", "agent": "operations_agent", "action": "create_task", "status": "succeeded", "entity_id": "T1"}},
        pending_step_id="s2",
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    from application.cognitive import CognitivePlanner
    engine = _make_engine(operations_agent=operations_agent, calendar_agent=calendar_agent, planner=CognitivePlanner())

    q = Question(text="cancel that please", context=ctx)
    ans = engine.ask(q)

    assert ans.clear_pending
    assert calendar_agent.create_entry_structured.call_count == 0
    assert operations_agent.process_event.call_count == 0


# =========================================================================
# 14. Cancellation does not falsely claim completed mutations were undone
# =========================================================================

def test_cancellation_does_not_falsely_claim_completed_mutations_undone():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    step1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task")
    step2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="create_event", dependencies=["s1"])
    plan = CognitivePlan(request_id="p_truth_cancel", original_message="Task and event", intent=IntentCategory.TASK_ACTION, execution_steps=[step1, step2])

    pending = PendingOperation(
        operation_id="op_truth",
        intent=IntentCategory.TASK_ACTION,
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        expires_at_iso=expires.isoformat(),
        plan_id="p_truth_cancel",
        original_plan=plan.model_dump(),
        completed_step_results={"s1": {"step_id": "s1", "action": "create_task", "status": "succeeded", "entity_id": "TASK-PERMANENT-1"}},
        pending_step_id="s2",
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    from application.cognitive import CognitivePlanner
    engine = _make_engine(planner=CognitivePlanner())

    q = Question(text="cancel operation", context=ctx)
    ans = engine.ask(q)

    assert "TASK-PERMANENT-1" in ans.text
    assert "not been undone" in ans.text.lower() or "already executed" in ans.text.lower()


# =========================================================================
# 15. Corrupt or incompatible persisted state fails safely
# =========================================================================

def test_corrupt_or_incompatible_persisted_state_fails_safely():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)

    # Persisted state with unsupported version 99 fails closed safely without crashing
    raw_dict = {
        "operation_id": "op_fut",
        "intent": IntentCategory.TASK_ACTION,
        "user_id": "U_ALICE",
        "channel_id": "C_MAIN",
        "thread_ts": "100.1",
        "expires_at_iso": expires.isoformat(),
        "state_version": 99,
        "plan_id": "p_fut",
        "original_plan": {"dummy": True},
    }

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=raw_dict)
    from application.cognitive import CognitivePlanner
    planner = CognitivePlanner()
    plan = planner.plan(Question(text="resume", context=ctx), context=ctx)

    assert not plan.action_required
    assert plan.requires_clarification is False


def test_state_version_validation_rejects_non_one_versions():
    """Verify that PendingOperation and planner accept only state_version == 1, rejecting 0, -1, 2, 99."""
    import pydantic
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    base_kwargs = dict(
        operation_id="op_v",
        intent=IntentCategory.TASK_ACTION,
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        expires_at_iso=expires.isoformat(),
        plan_id="p_v",
        original_plan={"dummy": True},
    )

    # Version 1 is explicitly supported and succeeds
    op_valid = PendingOperation(state_version=1, **base_kwargs)
    assert op_valid.state_version == 1

    # Versions 0, -1, 2, 99 raise ValidationError on construction
    for invalid_v in (0, -1, 2, 99):
        with pytest.raises(pydantic.ValidationError) as exc_info:
            PendingOperation(state_version=invalid_v, **base_kwargs)
        assert "Unsupported state_version" in str(exc_info.value)

        # Malformed persisted dictionary in conversation context fails closed without crashing
        raw_dict = dict(base_kwargs)
        raw_dict["state_version"] = invalid_v
        ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=raw_dict)
        assert ctx.get_typed_pending_operation() is None

        # Planner continuation fails closed safely if bypassed
        bypassed_op = PendingOperation.model_construct(state_version=invalid_v, **base_kwargs)
        from application.cognitive import CognitivePlanner
        planner = CognitivePlanner()
        plan = planner._plan_pending_continuation("req_test", "resume", bypassed_op)
        assert not plan.action_required
        assert plan.requires_clarification is False


# =========================================================================
# 16. An interrupted RUNNING step is not blindly retried
# =========================================================================

def test_interrupted_running_step_is_not_blindly_retried():
    operations_agent = MagicMock()
    step1 = ExecutionStep(step_id="step_running", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "Mutate"})
    plan = CognitivePlan(request_id="plan_running", original_message="Mutate", intent=IntentCategory.TASK_ACTION, execution_steps=[step1])

    # Preserved state has step_running in RUNNING status!
    initial_results = {
        "step_running": StepExecutionResult(
            step_id="step_running",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.RUNNING,
        )
    }

    from application.cognitive.multi_step_coordinator import MultiStepCoordinator
    coordinator = MultiStepCoordinator(step_executor=lambda *args: None)
    result = coordinator.execute(plan, initial_step_results=initial_results)

    # Coordinator must NOT execute step_running; marks it FAILED without retry
    assert result.step_results["step_running"].status == StepExecutionStatus.FAILED
    assert "uncertain" in result.step_results["step_running"].error.lower()
    assert result.status == MultiStepExecutionStatus.FAILED


# =========================================================================
# 17. An uncertain mutation outcome is not falsely reported as succeeded
# =========================================================================

def test_uncertain_mutation_outcome_not_falsely_reported():
    step1 = ExecutionStep(step_id="step_running", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "Mutate"})
    plan = CognitivePlan(request_id="plan_running", original_message="Mutate", intent=IntentCategory.TASK_ACTION, execution_steps=[step1])

    initial_results = {
        "step_running": StepExecutionResult(
            step_id="step_running",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.RUNNING,
        )
    }

    from application.cognitive.multi_step_coordinator import MultiStepCoordinator
    coordinator = MultiStepCoordinator(step_executor=lambda *args: None)
    result = coordinator.execute(plan, initial_step_results=initial_results)

    assert not result.is_all_succeeded
    assert "succeeded" not in result.overall_answer.lower()
    assert "uncertain" in result.overall_answer.lower()


# =========================================================================
# 18. Existing single-step pending-operation behavior remains compatible
# =========================================================================

def test_existing_single_step_pending_operation_behavior_remains_compatible():
    operations_agent = MagicMock()
    item = OperationalItem.create(item_type=OperationalItemType.TASK, summary="Single task", status=OperationalItemStatus.OPEN)
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_single_resumed",
    )

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    # Legacy single-step pending operation (no original_plan)
    pending = PendingOperation(
        operation_id="op_single",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        collected_entities={},
        missing_fields=["summary"],
        clarification_question="What is the task summary?",
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_MAIN", thread_ts="100.1", pending_operation=pending.model_dump())
    from application.cognitive import CognitivePlanner
    engine = _make_engine(operations_agent=operations_agent, planner=CognitivePlanner())

    q = Question(text="Single task", context=ctx)
    ans = engine.ask(q)

    assert operations_agent.process_event.call_count == 1
    assert "task_single_resumed" in ans.text
    assert ans.clear_pending


# =========================================================================
# 19. Existing Slack DM and thread-specific pending behavior remains compatible
# =========================================================================

def test_existing_slack_dm_and_thread_isolation_remains_compatible():
    repo = InMemoryConversationRepository()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)

    pending = PendingOperation(
        operation_id="op_dm",
        intent=IntentCategory.TASK_ACTION,
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        expires_at_iso=expires.isoformat(),
        plan_id="plan_dm",
        original_plan={"request_id": "plan_dm", "original_message": "...", "intent": "task_action", "execution_steps": []},
    )

    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1", channel_type="im")
    ctx = ctx.add_exchange(user_message="Schedule task", assistant_message="What time?", user_id="U_ALICE", pending_operation=pending.model_dump())
    repo.save(ctx)

    loaded = repo.get("D_ALICE", "100.1")
    assert loaded is not None
    assert loaded.pending_operation is not None
    assert loaded.get_typed_pending_operation(expected_user_id="U_ALICE") is not None
    # Mismatched user returns None
    assert loaded.get_typed_pending_operation(expected_user_id="U_EVE") is None


# =========================================================================
# 20. B1–B4 specialist dispatch behavior remains compatible
# =========================================================================

def test_b1_to_b4_dispatch_behavior_remains_compatible():
    operations_agent = MagicMock()
    item = OperationalItem.create(item_type=OperationalItemType.TASK, summary="B1 Task", status=OperationalItemStatus.OPEN)
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_b1_ok",
    )

    step = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "B1 Task"})
    plan = CognitivePlan(request_id="p_b1", original_message="Create B1 Task", intent=IntentCategory.TASK_ACTION, execution_steps=[step])
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    ans = engine.ask(Question(text="Create B1 Task"))

    assert operations_agent.process_event.call_count == 1
    assert "task_b1_ok" in ans.text
    assert ans.clear_pending


# =========================================================================
# 21. B5.1–B5.3 contracts and execution behavior remain compatible
# =========================================================================

def test_b5_1_to_b5_3_contracts_and_bridge_remain_compatible():
    operations_agent = MagicMock()
    item1 = OperationalItem.create(item_type=OperationalItemType.TASK, summary="Step 1", status=OperationalItemStatus.OPEN)
    item2 = OperationalItem.create(item_type=OperationalItemType.TASK, summary="Step 2", status=OperationalItemStatus.OPEN)
    operations_agent.process_event.side_effect = [
        OperationsResult(event_type=OrganizationEventType.TASK_CREATED, operation="created", item=item1, status=OperationalItemStatus.OPEN, affected_item_id="T1"),
        OperationsResult(event_type=OrganizationEventType.TASK_CREATED, operation="created", item=item2, status=OperationalItemStatus.OPEN, affected_item_id="T2"),
    ]

    step1 = ExecutionStep(step_id="step_1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", parameters={"summary": "Step 1"})
    step2 = ExecutionStep(step_id="step_2", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", dependencies=["step_1"], parameters={"summary": "Step 2", "prev_id": {"$step_ref": "step_1", "field": "entity_id"}})
    plan = CognitivePlan(request_id="p_multi", original_message="Step 1 and Step 2", intent=IntentCategory.TASK_ACTION, execution_steps=[step1, step2])
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    ans = engine.ask(Question(text="Step 1 and Step 2"))

    assert operations_agent.process_event.call_count == 2
    assert "T1" in ans.text and "T2" in ans.text
    assert ans.clear_pending
