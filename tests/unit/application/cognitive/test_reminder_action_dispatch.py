"""
Unit tests for POLIS Phase 3.3 Stage B3: Reminder Action Dispatch and Reliability.

Covers:
1. Valid task-linked reminder dispatch.
2. Missing task ID.
3. Task not found.
4. Missing target user.
5. Missing authenticated creator identity.
6. Missing channel context.
7. Missing source message timestamp.
8. Missing reminder time.
9. Invalid reminder time.
10. Invalid timezone.
11. Unsupported one-time reminder request.
12. Duplicate/idempotent scheduling.
13. Reminder service unavailable.
14. Reminder scheduling failure.
15. Successful execution clears pending state.
16. Failed execution preserves pending state.
17. No silent fall-through to generic answer synthesis.
18. Existing task dispatch from B1 remains unaffected.
19. Existing calendar dispatch from B2 remains unaffected.
20. Unrelated intents are not intercepted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from domain.operations import (
    InMemoryOperationalItemRepository,
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.reasoning.value_objects import (
    ActionType,
    Answer,
    CognitivePlan,
    ConversationContext,
    ExecutionStep,
    ExtractedEntities,
    IntentCategory,
    Question,
    TargetAgent,
)
from domain.reminders.repositories import InMemoryReminderRepository
from domain.reminders.services import ReminderService
from application.operations import (
    OperationalItemService,
    OperationsAgent,
)
from application.cognitive import SimpleCognitiveEngine


@pytest.fixture
def op_repo() -> InMemoryOperationalItemRepository:
    return InMemoryOperationalItemRepository()


@pytest.fixture
def op_service(op_repo) -> OperationalItemService:
    return OperationalItemService(op_repo)


@pytest.fixture
def reminder_repo() -> InMemoryReminderRepository:
    return InMemoryReminderRepository()


@pytest.fixture
def reminder_service(reminder_repo) -> ReminderService:
    return ReminderService(reminder_repo)


@pytest.fixture
def operations_agent(op_repo, op_service, reminder_service) -> OperationsAgent:
    return OperationsAgent(
        repository=op_repo,
        operational_item_service=op_service,
        reminder_service=reminder_service,
    )


@pytest.fixture
def existing_task(op_repo) -> OperationalItem:
    task = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Review Q3 Financial Audit",
        owner_id="U_BOB",
        owner_name="Bob Jones",
    )
    return op_repo.save(task)


def _make_reminder_plan(
    action: str = "create_reminder",
    action_type: ActionType = ActionType.CREATE,
    parameters: dict | None = None,
    entities: ExtractedEntities | None = None,
    intent: IntentCategory = IntentCategory.REMINDER_ACTION,
) -> CognitivePlan:
    return CognitivePlan(
        request_id="plan_test_rem",
        original_message="Reminder action request",
        intent=intent,
        intent_confidence=1.0,
        requested_outcome="Schedule task reminder",
        entities=entities or ExtractedEntities(),
        required_agents=[TargetAgent.REMINDER_SERVICE],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.REMINDER_SERVICE,
                action=action,
                action_type=action_type,
                parameters=dict(parameters or {}),
            )
        ],
        missing_information=[],
        requires_clarification=False,
        clarification_prompt=None,
        action_required=True,
        risk_level="low",
    )


# =========================================================================
# 1. Valid task-linked reminder dispatch
# =========================================================================

def test_valid_task_linked_reminder_dispatch(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
            "timezone_name": "UTC",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text=f"Remind Bob about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "Successfully scheduled task reminder" in ans.text
    assert "Review Q3 Financial Audit" in ans.text
    assert "U_BOB" in ans.text
    assert "09:00 and 17:00" in ans.text
    assert ans.clear_pending is True

    reminders = reminder_repo.list_all()
    assert len(reminders) == 1
    rem = reminders[0]
    assert rem.task == "Review Q3 Financial Audit"
    assert rem.target_user_id == "U_BOB"
    assert rem.creator_user_id == "U_ALICE"
    assert rem.channel_id == "C_AUDIT"
    assert rem.active is True


# =========================================================================
# 2. Missing task ID
# =========================================================================

def test_missing_task_id(operations_agent, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_reminder_plan(
        parameters={
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text="Remind Bob about the task", context=ctx)
    ans = engine.ask(q)

    assert "Cannot schedule task reminder: a valid task ID is required" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 3. Task not found
# =========================================================================

def test_task_not_found(operations_agent, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_reminder_plan(
        parameters={
            "task_id": "task_nonexistent_999",
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text="Remind Bob about task_nonexistent_999", context=ctx)
    ans = engine.ask(q)

    assert "task 'task_nonexistent_999' was not found" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 4. Missing target user
# =========================================================================

def test_missing_target_user(operations_agent, op_repo, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Create task with no owner
    task_no_owner = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Unassigned Infrastructure Task",
        owner_id="",
    )
    saved = op_repo.save(task_no_owner)
    task_id = str(saved.identifier.graph_id)

    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text=f"Remind about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "Cannot schedule task reminder: target user is required" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 5. Missing authenticated creator identity
# =========================================================================

def test_missing_authenticated_creator_identity(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    # Empty user_id in context and question
    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="")
    q = Question(text=f"Remind Bob about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "Requester identity is required" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 6. Missing channel context
# =========================================================================

def test_missing_channel_context(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    # Empty channel_id in context and parameters
    ctx = ConversationContext(channel_id="", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text=f"Remind Bob about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "Slack channel context is required" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 7. Missing source message timestamp
# =========================================================================

def test_missing_source_message_timestamp(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    # Empty thread_ts / message_ts in context and parameters
    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="", user_id="U_ALICE")
    q = Question(text=f"Remind Bob about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "source message timestamp is required" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 8. Missing reminder time
# =========================================================================

def test_missing_reminder_time(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text=f"Remind Bob about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "reminder times are required" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 9. Invalid reminder time
# =========================================================================

def test_invalid_reminder_time(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "25:99",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text=f"Remind Bob at 25:99 about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "invalid reminder time format" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 10. Invalid timezone
# =========================================================================

def test_invalid_timezone(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
            "timezone_name": "Saturn/Rings",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text=f"Remind Bob in Saturn/Rings about task {task_id}", context=ctx)
    ans = engine.ask(q)

    assert "invalid timezone 'Saturn/Rings'" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 11. Unsupported one-time reminder request
# =========================================================================

def test_unsupported_one_time_reminder_request(operations_agent, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_reminder_plan(
        parameters={
            "one_time": True,
            "duration_minutes": 15,
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text="Remind me in 15 minutes to call the vendor", context=ctx)
    ans = engine.ask(q)

    assert "only supports daily recurring task check-in reminders" in ans.text
    assert "One-time reminders and generic timers are not currently supported" in ans.text
    assert ans.clear_pending is False
    assert len(reminder_repo.list_all()) == 0


# =========================================================================
# 12. Duplicate/idempotent scheduling
# =========================================================================

def test_duplicate_idempotent_scheduling(operations_agent, existing_task, reminder_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text=f"Remind Bob about task {task_id}", context=ctx)

    # First scheduling
    ans1 = engine.ask(q)
    assert "Successfully scheduled task reminder" in ans1.text
    assert ans1.clear_pending is True
    assert len(reminder_repo.list_all()) == 1

    # Second scheduling attempt for same task and user
    ans2 = engine.ask(q)
    assert "A daily check-in reminder is already active" in ans2.text
    assert "No duplicate reminder was created" in ans2.text
    assert ans2.clear_pending is True
    assert len(reminder_repo.list_all()) == 1


# =========================================================================
# 13. Reminder service unavailable
# =========================================================================

def test_reminder_service_unavailable(op_repo, op_service):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # OperationsAgent without reminder_service
    agent_no_reminders = OperationsAgent(
        repository=op_repo,
        operational_item_service=op_service,
        reminder_service=None,
    )

    plan = _make_reminder_plan(
        parameters={
            "task_id": "task_1",
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=agent_no_reminders,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    ans = engine.ask(Question(text="Remind Bob about task", context=ctx))

    assert "Reminder service is currently unavailable" in ans.text
    assert ans.clear_pending is False


# =========================================================================
# 14. Reminder scheduling failure
# =========================================================================

def test_reminder_scheduling_failure(operations_agent, existing_task):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    # Simulate database / service failure
    operations_agent.schedule_task_reminder = MagicMock(
        side_effect=RuntimeError("Database connection lost during reminder creation")
    )

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    ans = engine.ask(Question(text=f"Remind Bob about task {task_id}", context=ctx))

    assert "Reminder scheduling failed: Database connection lost during reminder creation" in ans.text
    assert ans.clear_pending is False


# =========================================================================
# 15. Successful execution clears pending state
# =========================================================================

def test_successful_execution_clears_pending_state(operations_agent, existing_task):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_id = str(existing_task.identifier.graph_id)
    plan = _make_reminder_plan(
        parameters={
            "task_id": task_id,
            "target_user_id": "U_BOB",
            "time_1": "09:00",
            "time_2": "17:00",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(
        channel_id="C_AUDIT",
        thread_ts="1234.5678",
        user_id="U_ALICE",
        pending_operation={"operation_id": "op_rem_123"},
    )
    ans = engine.ask(Question(text=f"Remind Bob about task {task_id}", context=ctx))

    assert ans.clear_pending is True


# =========================================================================
# 16. Failed execution preserves pending state
# =========================================================================

def test_failed_execution_preserves_pending_state(operations_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Plan with missing task ID
    plan = _make_reminder_plan(
        parameters={},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(
        channel_id="C_AUDIT",
        thread_ts="1234.5678",
        user_id="U_ALICE",
        pending_operation={"operation_id": "op_rem_123"},
    )
    ans = engine.ask(Question(text="Remind me", context=ctx))

    assert ans.clear_pending is False


# =========================================================================
# 17. No silent fall-through to generic answer synthesis
# =========================================================================

def test_no_silent_fall_through_to_generic_answer_synthesis(operations_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    qa.retrieve_evidence = MagicMock()
    qa.answer_from_evidence = MagicMock()
    planner = MagicMock()

    plan = _make_reminder_plan(
        parameters={},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_AUDIT", thread_ts="1234.5678", user_id="U_ALICE")
    q = Question(text="Can we discuss policy and remind me?", context=ctx)
    ans = engine.ask(q)

    # Must NOT call evidence retrieval or answer synthesis
    qa.retrieve_evidence.assert_not_called()
    qa.answer_from_evidence.assert_not_called()

    # Must return explicit failure/clarification response
    assert "Cannot schedule task reminder: a valid task ID is required" in ans.text
    assert ans.clear_pending is False


# =========================================================================
# 18. Existing task dispatch from B1 remains unaffected
# =========================================================================

def test_existing_task_dispatch_from_b1_remains_unaffected(operations_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    task_plan = CognitivePlan(
        request_id="plan_task_b1",
        original_message="Create a task for staging deployment",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        requested_outcome="Create task",
        entities=ExtractedEntities(task_summary="Deploy to Staging"),
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.OPERATIONS_AGENT,
                action="create_task",
                action_type=ActionType.CREATE,
                parameters={"summary": "Deploy to Staging"},
            )
        ],
        missing_information=[],
        requires_clarification=False,
        clarification_prompt=None,
        action_required=True,
        risk_level="low",
    )
    planner.plan.return_value = task_plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_DEV", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Create task Deploy to Staging", context=ctx))

    assert "Task created successfully" in ans.text
    assert "Deploy to Staging" in ans.text
    assert ans.clear_pending is True


# =========================================================================
# 19. Existing calendar dispatch from B2 remains unaffected
# =========================================================================

def test_existing_calendar_dispatch_from_b2_remains_unaffected(operations_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    calendar_agent = MagicMock()
    calendar_agent.execute_structured.return_value = "Done! I've added it to the calendar.\n✅ Successfully scheduled Activity: Architecture Review"
    planner = MagicMock()

    cal_plan = CognitivePlan(
        request_id="plan_cal_b2",
        original_message="Schedule Architecture Review",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=1.0,
        requested_outcome="Schedule meeting",
        entities=ExtractedEntities(event_title="Architecture Review"),
        required_agents=[TargetAgent.CALENDAR_AGENT],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.CALENDAR_AGENT,
                action="create_event",
                action_type=ActionType.CREATE,
                parameters={
                    "title": "Architecture Review",
                    "start_time": "2026-11-20T10:00:00+05:30",
                    "audience_type": "team",
                    "audience_identifier": "dev",
                },
            )
        ],
        missing_information=[],
        requires_clarification=False,
        clarification_prompt=None,
        action_required=True,
        risk_level="low",
    )
    planner.plan.return_value = cal_plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Schedule Architecture Review", context=ctx))

    assert "Successfully scheduled" in ans.text
    assert "Architecture Review" in ans.text
    assert ans.clear_pending is True
    calendar_agent.execute_structured.assert_called_once()


# =========================================================================
# 20. Unrelated intents are not intercepted
# =========================================================================

def test_unrelated_intents_are_not_intercepted(operations_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    expected_ans = Answer(text="Our company was founded in 2024.", confidence=1.0)
    qa.answer.return_value = expected_ans
    planner = MagicMock()

    convo_plan = CognitivePlan(
        request_id="plan_convo",
        original_message="When was the company founded?",
        intent=IntentCategory.GENERAL_CONVERSATION,
        intent_confidence=1.0,
        requested_outcome="Answer query",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.GENERAL_REASONER],
        execution_steps=[],
        missing_information=[],
        requires_clarification=False,
        clarification_prompt=None,
        action_required=False,
        risk_level="low",
    )
    planner.plan.return_value = convo_plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        planner=planner,
    )

    operations_agent.schedule_task_reminder = MagicMock()

    q = Question(text="When was the company founded?")
    ans = engine.ask(q)

    assert ans == expected_ans
    operations_agent.schedule_task_reminder.assert_not_called()
