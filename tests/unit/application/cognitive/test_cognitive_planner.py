"""
Unit tests for Centralized Cognitive Planner (Phase 3.2 Stage 2).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from application.cognitive.cognitive_planner import CognitivePlanner
from domain.reasoning.value_objects.conversation_context import ConversationContext
from domain.reasoning.value_objects.question import Question
from domain.reasoning.value_objects.request_plan import (
    ActionType,
    CognitivePlan,
    IntentCategory,
    PendingOperation,
    TargetAgent,
)


def test_planner_greeting_fast_path():
    """Greetings should route directly to general_reasoner without calling LLM."""
    mock_llm = MagicMock()
    planner = CognitivePlanner(llm_client=mock_llm)

    plan = planner.plan("Good morning!")

    assert plan.intent == IntentCategory.GENERAL_CONVERSATION
    assert plan.required_agents == [TargetAgent.GENERAL_REASONER]
    assert plan.requires_clarification is False
    assert plan.action_required is False
    mock_llm.generate.assert_not_called()


def test_planner_activity_fast_path():
    """Attendance and work status queries should route directly to activity_service without calling LLM."""
    mock_llm = MagicMock()
    planner = CognitivePlanner(llm_client=mock_llm)

    plan = planner.plan("Who is currently on break?")

    assert plan.intent == IntentCategory.ACTIVITY_STATUS_QUERY
    assert plan.required_agents == [TargetAgent.ACTIVITY_SERVICE]
    assert plan.requires_clarification is False
    assert plan.execution_steps[0].agent == TargetAgent.ACTIVITY_SERVICE
    mock_llm.generate.assert_not_called()


def test_planner_calendar_schedule_missing_info_requires_clarification():
    """Calendar scheduling without date and time must require clarification rather than premature action."""
    planner = CognitivePlanner()

    plan = planner.plan("Schedule a meeting called Architecture Sync with Alice")

    assert plan.intent == IntentCategory.CALENDAR_ACTION
    assert plan.requires_clarification is True
    assert "date" in plan.missing_information
    assert "time" in plan.missing_information
    assert plan.action_required is False
    assert plan.clarification_prompt is not None
    assert "date and time" in plan.clarification_prompt.lower()
    assert plan.required_agents == [TargetAgent.CALENDAR_AGENT]


def test_planner_calendar_schedule_complete_creates_action():
    """Calendar scheduling with date, time, and title produces an action-ready plan."""
    planner = CognitivePlanner()

    plan = planner.plan("Schedule a meeting called Sprint Planning with Bob tomorrow at 3pm")

    assert plan.intent == IntentCategory.CALENDAR_ACTION
    assert plan.requires_clarification is False
    assert plan.action_required is True
    assert plan.required_agents == [TargetAgent.CALENDAR_AGENT]
    assert len(plan.execution_steps) == 1
    step = plan.execution_steps[0]
    assert step.action_type == ActionType.CREATE
    assert "tomorrow" in step.parameters["dates"]
    assert "3pm" in step.parameters["times"]
    assert step.parameters["title"] == "Sprint Planning"


def test_planner_pending_operation_cancel():
    """If an active pending operation exists and user asks to cancel, emit CANCEL_ACTION."""
    planner = CognitivePlanner()
    now = datetime.now(timezone.utc)

    pending = PendingOperation(
        operation_id="op_123",
        intent=IntentCategory.CALENDAR_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        collected_entities={"title": "Tech Talk"},
        missing_fields=["date", "time"],
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=(now + timedelta(minutes=15)).isoformat(),
    )
    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="100.1",
        user_id="U_ALICE",
        pending_operation=pending,
    )

    q = Question(text="Never mind, cancel it", context=ctx, target_user_id="U_ALICE")
    plan = planner.plan(q)

    assert plan.intent == IntentCategory.CANCEL_ACTION
    assert plan.action_required is True
    assert plan.requires_clarification is False
    assert plan.execution_steps[0].action_type == ActionType.CANCEL
    assert plan.execution_steps[0].parameters["operation_id"] == "op_123"


def test_planner_pending_operation_partial_continuation():
    """If user provides only part of the missing fields, prompt for the remaining fields."""
    planner = CognitivePlanner()
    now = datetime.now(timezone.utc)

    pending = PendingOperation(
        operation_id="op_456",
        intent=IntentCategory.CALENDAR_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        collected_entities={"title": "Design Review"},
        missing_fields=["date", "time"],
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="200.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=(now + timedelta(minutes=15)).isoformat(),
    )
    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="200.1",
        user_id="U_ALICE",
        pending_operation=pending,
    )

    # User only gives date ("tomorrow")
    q = Question(text="Let's do it tomorrow", context=ctx, target_user_id="U_ALICE")
    plan = planner.plan(q)

    assert plan.intent == IntentCategory.CLARIFICATION_RESPONSE
    assert plan.requires_clarification is True
    assert "time" in plan.missing_information
    assert "date" not in plan.missing_information
    assert plan.action_required is False


def test_planner_pending_operation_full_continuation():
    """When user provides all missing fields, produce action-ready plan with merged entities."""
    planner = CognitivePlanner()
    now = datetime.now(timezone.utc)

    pending = PendingOperation(
        operation_id="op_789",
        intent=IntentCategory.CALENDAR_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        collected_entities={"title": "Quarterly Planning"},
        missing_fields=["date", "time"],
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="300.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=(now + timedelta(minutes=15)).isoformat(),
    )
    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="300.1",
        user_id="U_ALICE",
        pending_operation=pending,
    )

    q = Question(text="Tomorrow at 2pm", context=ctx, target_user_id="U_ALICE")
    plan = planner.plan(q)

    assert plan.intent == IntentCategory.CALENDAR_ACTION
    assert plan.requires_clarification is False
    assert plan.action_required is True
    step = plan.execution_steps[0]
    assert step.action_type == ActionType.CREATE
    assert "tomorrow" in step.parameters["dates"]
    assert "2pm" in step.parameters["times"]
    assert step.parameters["title"] == "Quarterly Planning"


def test_planner_llm_json_success():
    """LLM client outputting valid JSON should be parsed into a validated CognitivePlan."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = """```json
    {
      "request_id": "plan_test",
      "original_message": "What tasks are assigned to Alice for project Titan?",
      "intent": "task_query",
      "intent_confidence": 0.95,
      "requested_outcome": "Query tasks for Alice on project Titan",
      "entities": {
        "employee_names": ["Alice"],
        "project_names": ["Titan"],
        "dates": [],
        "times": []
      },
      "required_agents": ["operations_agent"],
      "execution_steps": [
        {
          "step_id": "step_1",
          "agent": "operations_agent",
          "action": "query_tasks",
          "action_type": "read",
          "parameters": {"assignee": "Alice", "project": "Titan"},
          "dependencies": []
        }
      ],
      "missing_information": [],
      "requires_clarification": false,
      "clarification_prompt": null,
      "action_required": false,
      "risk_level": "low"
    }
    ```"""

    planner = CognitivePlanner(llm_client=mock_llm)
    plan = planner.plan("What tasks are assigned to Alice for project Titan?")

    assert isinstance(plan, CognitivePlan)
    assert plan.intent == IntentCategory.TASK_QUERY
    assert plan.required_agents == [TargetAgent.OPERATIONS_AGENT]
    assert plan.entities.employee_names == ["Alice"]
    assert plan.entities.project_names == ["Titan"]
    assert plan.execution_steps[0].agent == TargetAgent.OPERATIONS_AGENT


def test_planner_llm_malformed_falls_back_deterministically():
    """When LLM returns malformed text, planner gracefully falls back without crashing."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Sorry, I am an AI and cannot understand."

    planner = CognitivePlanner(llm_client=mock_llm)
    plan = planner.plan("What decisions were made about architecture?")

    assert isinstance(plan, CognitivePlan)
    assert plan.intent == IntentCategory.DECISION_QUERY
    assert plan.required_agents == [TargetAgent.OPERATIONS_AGENT]
    assert plan.execution_steps[0].agent == TargetAgent.OPERATIONS_AGENT


def test_planner_multi_agent_dependencies():
    """Planner supports multi-agent plans with validated step dependencies."""
    planner = CognitivePlanner()

    plan = planner.plan("What decisions were made and what are the related policies?")

    assert plan.intent == IntentCategory.MULTI_AGENT_QUERY
    assert TargetAgent.OPERATIONS_AGENT in plan.required_agents
    assert TargetAgent.GOVERNANCE_AGENT in plan.required_agents
    assert len(plan.execution_steps) == 2
    step_1 = plan.execution_steps[0]
    step_2 = plan.execution_steps[1]
    assert step_1.step_id == "step_1"
    assert step_2.step_id == "step_2"
    assert step_2.dependencies == ["step_1"]


def test_planner_task_action_missing_summary_requires_clarification():
    """Task creation without summary requires clarification."""
    planner = CognitivePlanner()
    plan = planner.plan("Create a task assigned to Bob")

    assert plan.intent == IntentCategory.TASK_ACTION
    assert plan.requires_clarification is True
    assert "task_summary" in plan.missing_information
    assert plan.action_required is False


def test_planner_task_action_with_summary_produces_create_step():
    """Task creation with summary produces action step."""
    planner = CognitivePlanner()
    plan = planner.plan("Create a task: 'Review security audit' assigned to Alice")

    assert plan.intent == IntentCategory.TASK_ACTION
    assert plan.requires_clarification is False
    assert plan.action_required is True
    assert plan.execution_steps[0].action_type == ActionType.CREATE
    assert "Review security audit" in plan.execution_steps[0].parameters["summary"]


def test_planner_reminder_missing_time_requires_clarification():
    """Reminder without time requires clarification."""
    planner = CognitivePlanner()
    plan = planner.plan("Remind me to submit expense reports")

    assert plan.intent == IntentCategory.REMINDER_ACTION
    assert plan.requires_clarification is True
    assert plan.action_required is False
    assert "time" in plan.missing_information


def test_planner_pending_operation_isolated_from_different_user():
    """A pending operation belonging to Alice cannot be resumed or cancelled by Bob."""
    planner = CognitivePlanner()
    now = datetime.now(timezone.utc)

    pending = PendingOperation(
        operation_id="op_alice_1",
        intent=IntentCategory.CALENDAR_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        collected_entities={"title": "Private Sync"},
        missing_fields=["date", "time"],
        user_id="U_ALICE",
        channel_id="C_MAIN",
        thread_ts="500.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=(now + timedelta(minutes=15)).isoformat(),
    )
    # In a shared thread, Bob's context holds Alice's pending operation from thread history
    ctx_bob = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="500.1",
        user_id="U_BOB",
        pending_operation=pending,
    )

    # Bob sends a message in the same thread
    q_bob = Question(text="Tomorrow at 3pm", context=ctx_bob)
    plan_bob = planner.plan(q_bob)

    # Must NOT continue Alice's calendar operation
    assert plan_bob.intent != IntentCategory.CALENDAR_ACTION
    assert plan_bob.intent != IntentCategory.CLARIFICATION_RESPONSE


def test_planner_llm_cycle_detected_falls_back_safely():
    """If LLM proposes dependency cycle in execution steps, planner catches validation error and falls back safely."""
    mock_llm = MagicMock()
    # LLM proposes step_1 depending on step_2 and step_2 depending on step_1 (cycle)
    mock_llm.generate.return_value = """{
      "request_id": "plan_cycle",
      "original_message": "What decisions were made about architecture?",
      "intent": "decision_query",
      "intent_confidence": 0.9,
      "requested_outcome": "Query decisions",
      "entities": {},
      "required_agents": ["operations_agent"],
      "execution_steps": [
        {"step_id": "step_1", "agent": "operations_agent", "action": "decisions", "action_type": "read", "parameters": {}, "dependencies": ["step_2"]},
        {"step_id": "step_2", "agent": "operations_agent", "action": "decisions_2", "action_type": "read", "parameters": {}, "dependencies": ["step_1"]}
      ],
      "missing_information": [],
      "requires_clarification": false,
      "clarification_prompt": null,
      "action_required": false,
      "risk_level": "low"
    }"""

    planner = CognitivePlanner(llm_client=mock_llm)
    plan = planner.plan("What decisions were made about architecture?")

    # Should not raise exception, but fallback to deterministic plan
    assert isinstance(plan, CognitivePlan)
    assert plan.intent == IntentCategory.DECISION_QUERY
    assert len(plan.execution_steps) == 1
