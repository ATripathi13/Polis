"""
Integration tests for Stage B5.3: Specialist Integration with MultiStepCoordinator in SimpleCognitiveEngine.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from application.cognitive import SimpleCognitiveEngine
from domain.common.identifier import Identifier
from domain.governance.entities import ApprovalRequest
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
    TargetAgent,
)
from domain.reasoning.value_objects.step_execution import (
    MultiStepExecutionStatus,
    StepExecutionResult,
    StepExecutionStatus,
)


def _make_engine(
    operations_agent=None,
    calendar_agent=None,
    governance_agent=None,
    planner=None,
    coordinator=None,
):
    pipeline = MagicMock()
    qa = MagicMock()
    if planner is None:
        planner = MagicMock()
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
# 1. Single-step plan retains existing behavior
# =========================================================================

def test_single_step_plan_retains_existing_behavior():
    operations_agent = MagicMock()
    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Write documentation",
        status=OperationalItemStatus.OPEN,
        priority=OperationalItemPriority.MEDIUM,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_single_1",
    )

    step = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Write documentation"},
    )
    plan = CognitivePlan(
        request_id="req_single",
        original_message="Create a task",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Create a task to write documentation")
    ans = engine.ask(q)

    assert isinstance(ans, Answer)
    assert ans.confidence == 1.0
    assert "task_single_1" in ans.text
    operations_agent.process_event.assert_called_once()


# =========================================================================
# 2. Two-step task workflow executes in dependency order
# =========================================================================

def test_two_step_task_workflow_executes_in_dependency_order():
    operations_agent = MagicMock()
    call_order = []

    def mock_process_event(event, **kwargs):
        call_order.append(event.event_type)
        if event.event_type == OrganizationEventType.TASK_CREATED:
            item = OperationalItem.create(
                item_type=OperationalItemType.TASK,
                summary="Build feature",
                status=OperationalItemStatus.OPEN,
            )
            return OperationsResult(
                event_type=OrganizationEventType.TASK_CREATED,
                operation="created",
                item=item,
                status=OperationalItemStatus.OPEN,
                affected_item_id="task_feat_100",
            )
        elif event.event_type == OrganizationEventType.TASK_UPDATED:
            item = OperationalItem.create(
                item_type=OperationalItemType.TASK,
                summary="Build feature",
                status=OperationalItemStatus.IN_PROGRESS,
            )
            return OperationsResult(
                event_type=OrganizationEventType.TASK_UPDATED,
                operation="updated",
                item=item,
                status=OperationalItemStatus.IN_PROGRESS,
                affected_item_id="task_feat_100",
            )
        raise ValueError(f"Unexpected event: {event.event_type}")

    operations_agent.process_event.side_effect = mock_process_event

    step1 = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Build feature"},
    )
    step2 = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="update_task",
        action_type=ActionType.UPDATE,
        dependencies=["step_1"],
        parameters={"task_id": {"$step_ref": "step_1", "field": "entity_id"}, "status": "in_progress"},
    )
    plan = CognitivePlan(
        request_id="req_multi_2",
        original_message="Create task and start it",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Create task and start it")
    ans = engine.ask(q)

    assert call_order == [OrganizationEventType.TASK_CREATED, OrganizationEventType.TASK_UPDATED]
    assert ans.confidence == 1.0
    assert "task_feat_100" in ans.text


# =========================================================================
# 3. Specialist-created entity ID passed to dependent step via $step_ref
# =========================================================================

def test_specialist_created_entity_id_passed_via_step_ref():
    operations_agent = MagicMock()
    passed_params = []

    def mock_process_event(event, **kwargs):
        meta = event.observations[0].metadata
        passed_params.append(meta)
        if event.event_type == OrganizationEventType.TASK_CREATED:
            item = OperationalItem.create(
                item_type=OperationalItemType.TASK,
                summary="Setup server",
                status=OperationalItemStatus.OPEN,
            )
            return OperationsResult(
                event_type=OrganizationEventType.TASK_CREATED,
                operation="created",
                item=item,
                status=OperationalItemStatus.OPEN,
                affected_item_id="SERVER-TASK-777",
            )
        elif event.event_type == OrganizationEventType.TASK_COMPLETED:
            item = OperationalItem.create(
                item_type=OperationalItemType.TASK,
                summary="Setup server",
                status=OperationalItemStatus.COMPLETED,
            )
            return OperationsResult(
                event_type=OrganizationEventType.TASK_COMPLETED,
                operation="completed",
                item=item,
                status=OperationalItemStatus.COMPLETED,
                affected_item_id="SERVER-TASK-777",
            )

    operations_agent.process_event.side_effect = mock_process_event

    step1 = ExecutionStep(
        step_id="step_create",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Setup server"},
    )
    step2 = ExecutionStep(
        step_id="step_complete",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="complete_task",
        action_type=ActionType.UPDATE,
        dependencies=["step_create"],
        parameters={"task_id": {"$step_ref": "step_create", "field": "task_id"}},
    )
    plan = CognitivePlan(
        request_id="req_ref",
        original_message="Create and complete",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Create and complete")
    ans = engine.ask(q)

    assert len(passed_params) == 2
    assert passed_params[1]["task_id"] == "SERVER-TASK-777"
    assert "SERVER-TASK-777" in ans.text


# =========================================================================
# 4. Failed first step blocks its dependent mutation
# =========================================================================

def test_failed_first_step_blocks_dependent_mutation():
    operations_agent = MagicMock()
    # First step fails
    operations_agent.process_event.side_effect = RuntimeError("Database write timeout")

    step1 = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Deploy cluster"},
    )
    step2 = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="update_task",
        action_type=ActionType.UPDATE,
        dependencies=["step_1"],
        parameters={"task_id": {"$step_ref": "step_1", "field": "entity_id"}},
    )
    plan = CognitivePlan(
        request_id="req_fail_block",
        original_message="Deploy and tag",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Deploy and tag")
    ans = engine.ask(q)

    # Only step 1 was attempted; step 2 was blocked
    assert operations_agent.process_event.call_count == 1
    assert "Blocked" in ans.text or "Failed" in ans.text
    assert not ans.clear_pending


# =========================================================================
# 5. Independent branch continues when another branch fails
# =========================================================================

def test_independent_branch_continues_when_another_branch_fails():
    operations_agent = MagicMock()
    governance_agent = MagicMock()

    # Operations fails
    operations_agent.process_event.side_effect = RuntimeError("Disk full")

    # Governance succeeds
    mock_appr = MagicMock()
    mock_appr.id = "appr_indep_1"
    mock_appr.title = "Resource request"
    mock_appr.target_object = "server_node_4"
    mock_appr.status = ApprovalStatus.PENDING
    mock_appr.requester_id = "U_USER_1"
    mock_appr.policy_id = None
    mock_appr.notes = None
    governance_agent.request_approval.return_value = mock_appr

    step1 = ExecutionStep(
        step_id="b1_task",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Crash task"},
    )
    step2 = ExecutionStep(
        step_id="b2_gov",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        dependencies=[],  # independent
        parameters={"title": "Resource request", "target_object": "server_node_4"},
    )
    plan = CognitivePlan(
        request_id="req_indep",
        original_message="Create task and request approval",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, governance_agent=governance_agent, planner=planner)
    context = ConversationContext(user_id="U_USER_1", channel_id="C_1", thread_ts="1234.56")
    q = Question(text="Create task and request approval", context=context)
    ans = engine.ask(q)

    assert operations_agent.process_event.call_count == 1
    assert governance_agent.request_approval.call_count == 1
    assert "b1_task" in ans.text and "Failed" in ans.text
    assert "b2_gov" in ans.text and "Succeeded" in ans.text


# =========================================================================
# 6. Calendar structured execution works through the bridge
# =========================================================================

def test_calendar_structured_execution_works_through_bridge():
    calendar_agent = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "cal_entry_999"
    mock_entry.title = "Sprint Planning"
    mock_entry.status.value = "scheduled"
    calendar_agent.create_entry_structured.return_value = mock_entry
    calendar_agent.format_confirmation.return_value = "✅ Event 'Sprint Planning' created successfully (ID: cal_entry_999)."

    step1 = ExecutionStep(
        step_id="step_cal",
        agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Sprint Planning",
            "start_time": "2026-11-01T10:00:00Z",
            "duration_minutes": 60,
            "audience_type": "organization",
            "audience_identifier": "all",
        },
    )
    step2 = ExecutionStep(
        step_id="step_cal_dummy",
        agent=TargetAgent.KNOWLEDGE_AGENT,
        action="retrieve",
        dependencies=["step_cal"],
        parameters={},
    )
    plan = CognitivePlan(
        request_id="req_cal",
        original_message="Schedule sprint planning",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(calendar_agent=calendar_agent, planner=planner)
    context = ConversationContext(user_id="U_CAL_USER", channel_id="C_CAL", thread_ts="1234.56")
    q = Question(text="Schedule sprint planning", context=context)
    ans = engine.ask(q)

    assert calendar_agent.create_entry_structured.call_count == 1
    assert "cal_entry_999" in ans.text


# =========================================================================
# 7. Reminder execution works through the bridge
# =========================================================================

def test_reminder_execution_works_through_bridge():
    operations_agent = MagicMock()

    # Step 1: create task
    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Security review",
        status=OperationalItemStatus.OPEN,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_sec_55",
    )
    operations_agent.get_item.return_value = task_item
    operations_agent.find_task_reminder.return_value = None

    # Step 2: schedule reminder
    mock_rem = MagicMock()
    mock_rem.identifier.graph_id = "rem_graph_123"
    operations_agent.schedule_task_reminder.return_value = mock_rem

    step1 = ExecutionStep(
        step_id="s1_task",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Security review"},
    )
    step2 = ExecutionStep(
        step_id="s2_rem",
        agent=TargetAgent.REMINDER_SERVICE,
        action="schedule_reminder",
        dependencies=["s1_task"],
        parameters={
            "task_id": {"$step_ref": "s1_task", "field": "task_id"},
            "target_user_id": "U_SEC_ANALYST",
            "times": ["09:00", "17:00"],
            "timezone": "UTC",
        },
    )
    plan = CognitivePlan(
        request_id="req_rem",
        original_message="Create task and remind analyst",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.REMINDER_SERVICE],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    context = ConversationContext(user_id="U_CREATOR", channel_id="C_SEC", thread_ts="112233.44")
    q = Question(text="Create task and remind analyst", context=context)
    ans = engine.ask(q)

    assert operations_agent.schedule_task_reminder.call_count == 1
    call_args = operations_agent.schedule_task_reminder.call_args[1]
    assert call_args["task_id"] == "task_sec_55"
    assert call_args["target_user_id"] == "U_SEC_ANALYST"
    assert call_args["creator_user_id"] == "U_CREATOR"
    assert ans.confidence == 1.0


# =========================================================================
# 8. Governance execution works through the bridge
# =========================================================================

def test_governance_execution_works_through_bridge():
    governance_agent = MagicMock()
    mock_approval = MagicMock()
    mock_approval.id = "appr_bridge_101"
    mock_approval.title = "Database Migration Approval"
    mock_approval.target_object = "db_cluster_prod"
    mock_approval.status = ApprovalStatus.PENDING
    mock_approval.requester_id = "U_LEAD"
    mock_approval.policy_id = None
    mock_approval.notes = None
    governance_agent.request_approval.return_value = mock_approval

    step1 = ExecutionStep(
        step_id="step_appr",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        parameters={
            "title": "Database Migration Approval",
            "target_object": "db_cluster_prod",
        },
    )
    step2 = ExecutionStep(
        step_id="step_appr_noop",
        agent=TargetAgent.KNOWLEDGE_AGENT,
        action="retrieve",
        dependencies=["step_appr"],
        parameters={},
    )
    plan = CognitivePlan(
        request_id="req_gov",
        original_message="Request approval for migration",
        intent=IntentCategory.GOVERNANCE_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(governance_agent=governance_agent, planner=planner)
    context = ConversationContext(user_id="U_LEAD", channel_id="C_OPS", thread_ts="1234.56")
    q = Question(text="Request approval for migration", context=context)
    ans = engine.ask(q)

    assert governance_agent.request_approval.call_count == 1
    assert "appr_bridge_101" in ans.text


# =========================================================================
# 9. Authenticated identity preserved across all specialist dispatches
# =========================================================================

def test_authenticated_identity_preserved_across_all_specialist_dispatches():
    operations_agent = MagicMock()
    governance_agent = MagicMock()

    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Audit config",
        status=OperationalItemStatus.OPEN,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_audit_1",
    )
    mock_appr = MagicMock()
    mock_appr.id = "appr_audit_1"
    mock_appr.title = "Audit Approval"
    mock_appr.target_object = "audit_log"
    mock_appr.status = ApprovalStatus.PENDING
    mock_appr.requester_id = "U_AUTH_42"
    mock_appr.policy_id = None
    mock_appr.notes = None
    governance_agent.request_approval.return_value = mock_appr

    step1 = ExecutionStep(
        step_id="step_task",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Audit config"},
    )
    step2 = ExecutionStep(
        step_id="step_gov",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        dependencies=["step_task"],
        # Notice: parameters attempts to spoof requester as "MALICIOUS_USER"
        parameters={"title": "Audit Approval", "target_object": "audit_log", "requester_id": "MALICIOUS_USER"},
    )
    plan = CognitivePlan(
        request_id="req_auth",
        original_message="Run audit",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, governance_agent=governance_agent, planner=planner)
    # Context has authoritative user_id
    context = ConversationContext(user_id="U_AUTH_42", channel_id="C_AUDIT", thread_ts="1234.56")
    q = Question(text="Run audit", context=context)
    ans = engine.ask(q)

    # Verify governance request_approval was called with authoritative U_AUTH_42, NOT MALICIOUS_USER
    gov_kwargs = governance_agent.request_approval.call_args[1]
    assert gov_kwargs["requester_id"] == "U_AUTH_42"


# =========================================================================
# 10. Invalid or unavailable references never invoke dependent specialist
# =========================================================================

def test_invalid_or_unavailable_references_never_invoke_dependent_specialist():
    operations_agent = MagicMock()
    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Create repo",
        status=OperationalItemStatus.OPEN,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_repo_1",
    )

    step1 = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Create repo"},
    )
    # References non-existent field "non_existent_field"
    step2 = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="update_task",
        dependencies=["step_1"],
        parameters={"task_id": {"$step_ref": "step_1", "field": "non_existent_field"}},
    )
    plan = CognitivePlan(
        request_id="req_inv_ref",
        original_message="Create and update",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Create and update")
    ans = engine.ask(q)

    # Only step 1 was executed; step 2 was rejected before invoking specialist
    assert operations_agent.process_event.call_count == 1
    assert "step_2" in ans.text and ("Blocked" in ans.text or "Failed" in ans.text)


# =========================================================================
# 11. Clarification-required results do not permit dependent execution
# =========================================================================

def test_clarification_required_results_do_not_permit_dependent_execution():
    operations_agent = MagicMock()

    # Step 1 lacks summary, so _execute_task_step returns clarification required
    step1 = ExecutionStep(
        step_id="step_ask",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={},  # No summary!
    )
    step2 = ExecutionStep(
        step_id="step_dep",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="update_task",
        dependencies=["step_ask"],
        parameters={"task_id": {"$step_ref": "step_ask", "field": "entity_id"}},
    )
    plan = CognitivePlan(
        request_id="req_clar",
        original_message="Create task",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Create task")
    ans = engine.ask(q)

    # OperationsAgent process_event was never called because step 1 was intercepted as clarification required
    assert operations_agent.process_event.call_count == 0
    assert "description" in ans.text.lower() or "summary" in ans.text.lower()
    assert not ans.clear_pending


# =========================================================================
# 12. Specialist exceptions become controlled step failures
# =========================================================================

def test_specialist_exceptions_become_controlled_step_failures():
    operations_agent = MagicMock()
    operations_agent.process_event.side_effect = ZeroDivisionError("Math error in specialist")

    step1 = ExecutionStep(
        step_id="s1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Crash math"},
    )
    step2 = ExecutionStep(
        step_id="s2",
        agent=TargetAgent.KNOWLEDGE_AGENT,
        action="retrieve",
        dependencies=[],
        parameters={},
    )
    plan = CognitivePlan(
        request_id="req_exc",
        original_message="Do crash and check",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.KNOWLEDGE_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Do crash and check")
    ans = engine.ask(q)

    # Engine did not crash; returned controlled failure summary
    assert "Math error in specialist" in ans.text or "s1" in ans.text
    assert not ans.clear_pending


# =========================================================================
# 13. Multi-step responses accurately report partial success and blocked steps
# =========================================================================

def test_multistep_responses_accurately_report_partial_success_and_blocked():
    operations_agent = MagicMock()

    # Step 1 succeeds
    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Step 1 work",
        status=OperationalItemStatus.OPEN,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="task_step1_ok",
    )

    # Step 2 has an invalid output reference to step 1
    step1 = ExecutionStep(
        step_id="step_ok",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Step 1 work"},
    )
    step2 = ExecutionStep(
        step_id="step_bad_ref",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="update_task",
        dependencies=["step_ok"],
        parameters={"task_id": {"$step_ref": "step_ok", "field": "missing_field"}},
    )
    step3 = ExecutionStep(
        step_id="step_transitive_block",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="complete_task",
        dependencies=["step_bad_ref"],
        parameters={"task_id": {"$step_ref": "step_bad_ref", "field": "entity_id"}},
    )
    plan = CognitivePlan(
        request_id="req_partial",
        original_message="Run sequence",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2, step3],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Run sequence")
    ans = engine.ask(q)

    # Response clearly reports step_ok succeeded, step_bad_ref failed/blocked, and step_transitive_block blocked
    assert "step_ok" in ans.text and "Succeeded" in ans.text
    assert "step_bad_ref" in ans.text
    assert "step_transitive_block" in ans.text and "Blocked" in ans.text


# =========================================================================
# 14. No mutation is falsely reported as successful
# =========================================================================

def test_no_mutation_is_falsely_reported_as_successful():
    operations_agent = MagicMock()
    operations_agent.process_event.side_effect = ValueError("Duplicate task detected")

    step1 = ExecutionStep(
        step_id="step_fail",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Duplicate task"},
    )
    step2 = ExecutionStep(
        step_id="step_dep",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="update_task",
        dependencies=["step_fail"],
        parameters={"task_id": {"$step_ref": "step_fail", "field": "entity_id"}},
    )
    plan = CognitivePlan(
        request_id="req_nofalse",
        original_message="Create duplicate",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(operations_agent=operations_agent, planner=planner)
    q = Question(text="Create duplicate")
    ans = engine.ask(q)

    # Must NOT report "succeeded" or claim task was created
    assert "All execution steps succeeded" not in ans.text
    assert "Task created successfully" not in ans.text
    assert not ans.clear_pending


# =========================================================================
# 15. Existing B1–B4 behavior remains compatible
# =========================================================================

def test_existing_b1_to_b4_behavior_remains_compatible():
    operations_agent = MagicMock()
    calendar_agent = MagicMock()
    governance_agent = MagicMock()

    # Step 1: Operations task creation
    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Quarterly Planning",
        status=OperationalItemStatus.OPEN,
    )
    operations_agent.process_event.return_value = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id="TASK-QP-01",
    )

    # Step 2: Calendar meeting creation
    mock_cal = MagicMock()
    mock_cal.entry_id = "CAL-QP-01"
    mock_cal.title = "Quarterly Planning Review"
    mock_cal.status.value = "scheduled"
    calendar_agent.create_entry_structured.return_value = mock_cal
    calendar_agent.format_confirmation.return_value = "Calendar event created."

    # Step 3: Governance approval request
    mock_gov = MagicMock()
    mock_gov.id = "GOV-QP-01"
    mock_gov.title = "Budget Approval"
    mock_gov.target_object = "TASK-QP-01"
    mock_gov.status = ApprovalStatus.PENDING
    mock_gov.requester_id = "U_LEAD"
    mock_gov.policy_id = None
    mock_gov.notes = None
    governance_agent.request_approval.return_value = mock_gov

    step1 = ExecutionStep(
        step_id="step_task",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        parameters={"summary": "Quarterly Planning"},
    )
    step2 = ExecutionStep(
        step_id="step_cal",
        agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        dependencies=["step_task"],
        parameters={
            "title": "Quarterly Planning Review",
            "start_time": "2026-11-05T14:00:00Z",
            "duration_minutes": 60,
            "audience_type": "organization",
            "audience_identifier": "all",
        },
    )
    step3 = ExecutionStep(
        step_id="step_gov",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        dependencies=["step_task"],
        parameters={
            "title": "Budget Approval",
            "target_object": {"$step_ref": "step_task", "field": "entity_id"},
        },
    )
    plan = CognitivePlan(
        request_id="req_full_composite",
        original_message="Setup quarterly planning with calendar and budget approval",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.CALENDAR_AGENT, TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step1, step2, step3],
    )
    planner = MagicMock()
    planner.plan.return_value = plan

    engine = _make_engine(
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
        governance_agent=governance_agent,
        planner=planner,
    )
    context = ConversationContext(user_id="U_LEAD", channel_id="C_PLANNING", thread_ts="1234.56")
    q = Question(text="Setup quarterly planning", context=context)
    ans = engine.ask(q)

    assert operations_agent.process_event.call_count == 1
    assert calendar_agent.create_entry_structured.call_count == 1
    assert governance_agent.request_approval.call_count == 1
    assert ans.confidence == 1.0
    assert ans.clear_pending
    assert "TASK-QP-01" in ans.text
    assert "GOV-QP-01" in ans.text
