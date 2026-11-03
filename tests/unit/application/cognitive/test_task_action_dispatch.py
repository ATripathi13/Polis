"""
Unit tests for Task Action Dispatch in SimpleCognitiveEngine (POLIS Phase 3.3).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from application.cognitive import CognitivePlanner, SimpleCognitiveEngine
from application.operations import OperationsAgent
from domain.common.identifier import Identifier
from domain.operations import (
    InMemoryOperationalItemRepository,
    InvalidLifecycleTransitionError,
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
    OperationalItemNotFoundError,
    OperationsResult,
)
from domain.organization import (
    OrganizationEventType,
)
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


def _make_cognitive_plan(
    *,
    intent: IntentCategory = IntentCategory.TASK_ACTION,
    action_type: ActionType = ActionType.CREATE,
    action: str = "create_task",
    agent: TargetAgent = TargetAgent.OPERATIONS_AGENT,
    parameters: dict | None = None,
    action_required: bool = True,
    entities: ExtractedEntities | None = None,
    request_id: str = "req_task_123",
) -> CognitivePlan:
    step = ExecutionStep(
        step_id="step_1",
        agent=agent,
        action=action,
        action_type=action_type,
        parameters=parameters or {},
    )
    return CognitivePlan(
        request_id=request_id,
        original_message="Create a task",
        intent=intent,
        intent_confidence=1.0,
        requested_outcome="Execute task mutation",
        entities=entities or ExtractedEntities(),
        required_agents=[agent],
        execution_steps=[step],
        missing_information=[],
        requires_clarification=False,
        action_required=action_required,
        risk_level="low",
    )


def test_valid_task_creation_dispatches_task_created():
    """Valid task creation dispatches TASK_CREATED to OperationsAgent."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.CREATE,
        action="create_task",
        parameters={
            "summary": "Deploy authentication service",
            "assignee": "Alice",
            "owner_id": "U_ALICE",
            "priority": "high",
        },
    )
    planner.plan.return_value = plan

    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Deploy authentication service",
        status=OperationalItemStatus.OPEN,
        priority=OperationalItemPriority.HIGH,
        owner_id="U_ALICE",
        owner_name="Alice",
    )
    mock_result = OperationsResult(
        event_type=OrganizationEventType.TASK_CREATED,
        operation="created",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        affected_item_id=str(task_item.identifier.graph_id),
    )
    operations_agent.process_event.return_value = mock_result

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Create a high priority task for Alice to deploy authentication service")
    ans = engine.ask(q)

    assert "created successfully" in ans.text.lower()
    assert "deploy authentication service" in ans.text.lower()
    assert str(task_item.identifier.graph_id) in ans.text
    assert ans.clear_pending is True

    operations_agent.process_event.assert_called_once()
    event_arg = operations_agent.process_event.call_args[0][0]
    assert event_arg.event_type == OrganizationEventType.TASK_CREATED
    assert event_arg.summary == "Deploy authentication service"
    assert event_arg.observations[0].metadata["priority"] == "high"
    assert event_arg.observations[0].metadata["assignee"] == "Alice"
    assert event_arg.observations[0].metadata["owner_id"] == "U_ALICE"


def test_valid_task_update_dispatches_task_updated():
    """Valid task update dispatches TASK_UPDATED to OperationsAgent."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.UPDATE,
        action="update_task",
        parameters={
            "task_id": "task_456",
            "status": "in_progress",
            "summary": "Updated task title",
        },
    )
    planner.plan.return_value = plan

    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Updated task title",
        status=OperationalItemStatus.IN_PROGRESS,
    )
    mock_result = OperationsResult(
        event_type=OrganizationEventType.TASK_UPDATED,
        operation="updated",
        item=task_item,
        status=OperationalItemStatus.IN_PROGRESS,
        affected_item_id="task_456",
    )
    operations_agent.process_event.return_value = mock_result

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Update task task_456 to in progress")
    ans = engine.ask(q)

    assert "updated successfully" in ans.text.lower()
    assert "task_456" in ans.text
    assert ans.clear_pending is True

    operations_agent.process_event.assert_called_once()
    event_arg = operations_agent.process_event.call_args[0][0]
    assert event_arg.event_type == OrganizationEventType.TASK_UPDATED
    assert event_arg.observations[0].metadata["item_id"] == "task_456"
    assert event_arg.observations[0].metadata["status"] == "in_progress"


def test_valid_task_completion_dispatches_task_completed():
    """Valid task completion dispatches TASK_COMPLETED to OperationsAgent."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.UPDATE,
        action="complete_task",
        parameters={
            "task_id": "task_789",
        },
    )
    planner.plan.return_value = plan

    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Finished task",
        status=OperationalItemStatus.COMPLETED,
    )
    mock_result = OperationsResult(
        event_type=OrganizationEventType.TASK_COMPLETED,
        operation="completed",
        item=task_item,
        status=OperationalItemStatus.COMPLETED,
        affected_item_id="task_789",
    )
    operations_agent.process_event.return_value = mock_result

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Mark task task_789 as completed")
    ans = engine.ask(q)

    assert "completed successfully" in ans.text.lower()
    assert "task_789" in ans.text
    assert ans.clear_pending is True

    operations_agent.process_event.assert_called_once()
    event_arg = operations_agent.process_event.call_args[0][0]
    assert event_arg.event_type == OrganizationEventType.TASK_COMPLETED
    assert event_arg.observations[0].metadata["item_id"] == "task_789"


def test_missing_task_summary_does_not_invoke_process_event():
    """Missing task summary does not call process_event and prompts user."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.CREATE,
        action="create_task",
        parameters={"priority": "low"},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Create a task")
    ans = engine.ask(q)

    assert "description or summary" in ans.text.lower()
    assert ans.clear_pending is False
    operations_agent.process_event.assert_not_called()


def test_missing_target_task_id_for_update_does_not_invoke_process_event():
    """Missing target task ID for an update operation does not call process_event."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.UPDATE,
        action="update_task",
        parameters={"status": "in_progress"},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Update the task to in progress")
    ans = engine.ask(q)

    assert "which task would you like to update" in ans.text.lower()
    assert ans.clear_pending is False
    operations_agent.process_event.assert_not_called()


def test_missing_target_task_id_for_completion_does_not_invoke_process_event():
    """Missing target task ID for task completion does not call process_event."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.UPDATE,
        action="complete_task",
        parameters={},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Mark task as complete")
    ans = engine.ask(q)

    assert "which task would you like to complete" in ans.text.lower()
    assert ans.clear_pending is False
    operations_agent.process_event.assert_not_called()


def test_unsupported_priority_is_rejected():
    """Unsupported priority string is explicitly rejected without invoking process_event."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.CREATE,
        action="create_task",
        parameters={"summary": "Urgent bugfix", "priority": "super-critical-urgent"},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Create task with super-critical-urgent priority")
    ans = engine.ask(q)

    assert "invalid priority" in ans.text.lower()
    assert "super-critical-urgent" in ans.text
    assert ans.clear_pending is False
    operations_agent.process_event.assert_not_called()


def test_operations_agent_unavailable_produces_explicit_failure():
    """When OperationsAgent is None, the engine returns an explicit failure without crashing."""
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.CREATE,
        action="create_task",
        parameters={"summary": "Write documentation"},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=None,
        planner=planner,
    )

    q = Question(text="Create a task to write documentation")
    ans = engine.ask(q)

    assert "not configured" in ans.text.lower()
    assert ans.confidence == 0.0
    assert ans.clear_pending is False


def test_domain_lifecycle_rejection_produces_explicit_failure():
    """InvalidLifecycleTransitionError from domain is caught and reported cleanly."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.UPDATE,
        action="update_task",
        parameters={"task_id": "task_closed", "status": "in_progress"},
    )
    planner.plan.return_value = plan

    operations_agent.process_event.side_effect = InvalidLifecycleTransitionError(
        "Cannot transition task from 'closed' to 'in_progress'."
    )

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Reopen closed task")
    ans = engine.ask(q)

    assert "transition rejected" in ans.text.lower()
    assert "closed" in ans.text
    assert ans.clear_pending is False


def test_not_found_task_update_produces_explicit_failure():
    """OperationalItemNotFoundError from domain produces an explicit failure."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.UPDATE,
        action="update_task",
        parameters={"task_id": "non_existent_id", "status": "completed"},
    )
    planner.plan.return_value = plan

    operations_agent.process_event.side_effect = OperationalItemNotFoundError(
        "Referenced operational task 'non_existent_id' was not found."
    )

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Complete task non_existent_id")
    ans = engine.ask(q)

    assert "task not found" in ans.text.lower()
    assert "non_existent_id" in ans.text
    assert ans.clear_pending is False


def test_idempotent_no_op_result_is_not_reported_as_newly_created():
    """A no-op/idempotent result explicitly states that no changes were made."""
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.UPDATE,
        action="update_task",
        parameters={"task_id": "task_100", "status": "open"},
    )
    planner.plan.return_value = plan

    task_item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Existing task",
        status=OperationalItemStatus.OPEN,
    )
    mock_result = OperationsResult(
        event_type=OrganizationEventType.TASK_UPDATED,
        operation="no_op",
        item=task_item,
        status=OperationalItemStatus.OPEN,
        idempotent=True,
        affected_item_id="task_100",
    )
    operations_agent.process_event.return_value = mock_result

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    q = Question(text="Set task task_100 to open")
    ans = engine.ask(q)

    assert "no changes were made" in ans.text.lower()
    assert "already in status open" in ans.text.lower()
    assert ans.clear_pending is True


def test_task_dispatch_does_not_intercept_unrelated_requests():
    """Task dispatch does not intercept calendar or general conversation requests."""
    pipeline = MagicMock()
    qa = MagicMock()
    calendar_agent = MagicMock()
    calendar_agent.handle_message.return_value = "Calendar event created."
    operations_agent = MagicMock()
    planner = MagicMock()

    # 1. Calendar action
    cal_plan = _make_cognitive_plan(
        intent=IntentCategory.CALENDAR_ACTION,
        agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
    )
    planner.plan.return_value = cal_plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    q_cal = Question(text="Schedule a meeting tomorrow at 10am")
    ans_cal = engine.ask(q_cal)

    assert ans_cal.text == "Calendar event created."
    operations_agent.process_event.assert_not_called()

    # 2. General conversation
    gen_plan = CognitivePlan(
        request_id="req_gen_1",
        original_message="Hello",
        intent=IntentCategory.GENERAL_CONVERSATION,
        intent_confidence=1.0,
        requested_outcome="Greeting",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.GENERAL_REASONER],
        execution_steps=[],
        missing_information=[],
        requires_clarification=False,
        action_required=False,
        risk_level="low",
    )
    planner.plan.return_value = gen_plan
    qa.answer.return_value = Answer(text="Hello! How can I help you?")

    q_gen = Question(text="Hello")
    ans_gen = engine.ask(q_gen)

    assert ans_gen.text == "Hello! How can I help you?"
    operations_agent.process_event.assert_not_called()


def test_repeated_requests_preserve_existing_idempotency_with_real_operations_agent():
    """Integration test with real OperationsAgent preserving repository idempotency."""
    repo = InMemoryOperationalItemRepository()
    real_operations_agent = OperationsAgent(repository=repo)
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_cognitive_plan(
        action_type=ActionType.CREATE,
        action="create_task",
        parameters={
            "summary": "Implement OAuth2 login",
            "priority": "medium",
        },
        request_id="req_idempotent_1",
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=real_operations_agent,
        planner=planner,
    )

    q = Question(text="Create task to implement OAuth2 login")

    # First execution: created
    ans1 = engine.ask(q)
    assert "created successfully" in ans1.text.lower()
    assert ans1.clear_pending is True

    # Second execution with identical source_event_id: idempotent no_op
    ans2 = engine.ask(q)
    assert "already in status" in ans2.text.lower() or "no changes were made" in ans2.text.lower()
    assert ans2.clear_pending is True

    # Confirm only 1 item was saved in the repository
    open_tasks = repo.find_open(item_type=OperationalItemType.TASK)
    assert len(open_tasks) == 1
    assert open_tasks[0].summary == "Implement OAuth2 login"
