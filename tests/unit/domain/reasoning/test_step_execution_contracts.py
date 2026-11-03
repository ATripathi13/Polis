"""
Unit tests for Stage B5.1 execution contracts:
StepExecutionStatus, MultiStepExecutionStatus, StepExecutionResult,
MultiStepExecutionResult, StepOutputReference, and parameter resolution.
"""

import pytest
from pydantic import ValidationError

from domain.reasoning.value_objects import (
    ActionType,
    ExecutionStep,
    MultiStepExecutionResult,
    MultiStepExecutionStatus,
    StepExecutionResult,
    StepExecutionStatus,
    StepOutputReference,
    TargetAgent,
    EmptyOutputValueError,
    OutputFieldNotFoundError,
    OutputReferenceError,
    OutputTypeMismatchError,
    SourceStepNotFoundError,
    SourceStepNotSucceededError,
    UndeclaredDependencyReferenceError,
    resolve_step_parameters,
)


def test_step_execution_status_values():
    """Verify explicit execution states."""
    assert StepExecutionStatus.PENDING == "pending"
    assert StepExecutionStatus.RUNNING == "running"
    assert StepExecutionStatus.SUCCEEDED == "succeeded"
    assert StepExecutionStatus.FAILED == "failed"
    assert StepExecutionStatus.BLOCKED == "blocked"
    assert StepExecutionStatus.SKIPPED == "skipped"


def test_multi_step_execution_status_values():
    """Verify overall multi-step execution outcome statuses."""
    assert MultiStepExecutionStatus.ALL_SUCCEEDED == "all_succeeded"
    assert MultiStepExecutionStatus.PARTIAL_SUCCESS == "partial_success"
    assert MultiStepExecutionStatus.FAILED == "failed"
    assert MultiStepExecutionStatus.BLOCKED == "blocked"
    assert MultiStepExecutionStatus.CLARIFICATION_REQUIRED == "clarification_required"


def test_step_execution_result_construction_and_output_lookup():
    """Verify structured result construction and safe field lookup."""
    res = StepExecutionResult(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        status=StepExecutionStatus.SUCCEEDED,
        entity_id="task-12345",
        entity_type="task",
        output_fields={"task_id": "task-12345", "priority": "high", "assignee": "U_ALICE"},
        answer="Created task task-12345.",
        warnings=["Non-blocking deadline warning"],
        error=None,
    )

    assert res.step_id == "step_1"
    assert res.status == StepExecutionStatus.SUCCEEDED
    assert res.get_output("task_id") == "task-12345"
    assert res.get_output("entity_id") == "task-12345"
    assert res.get_output("entity_type") == "task"
    assert res.get_output("priority") == "high"
    assert res.get_output("non_existent") is None
    assert not res.is_terminal_failure


def test_step_execution_result_does_not_infer_id_from_answer():
    """Verify domain IDs are strictly taken from structured fields, not answer text."""
    res = StepExecutionResult(
        step_id="step_read",
        agent=TargetAgent.KNOWLEDGE_AGENT,
        action="search",
        status=StepExecutionStatus.SUCCEEDED,
        entity_id=None,
        entity_type=None,
        output_fields={},
        answer="I found task-99999 in the documentation.",
    )
    assert res.get_output("entity_id") is None
    assert res.get_output("task_id") is None


def test_multi_step_execution_result_aggregation():
    """Verify aggregation properties for overall plan execution results."""
    res1 = StepExecutionResult(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        status=StepExecutionStatus.SUCCEEDED,
        entity_id="t-1",
    )
    res2 = StepExecutionResult(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        status=StepExecutionStatus.FAILED,
        error="Calendar conflict",
    )
    res3 = StepExecutionResult(
        step_id="step_3",
        agent=TargetAgent.REMINDER_SERVICE,
        action="remind",
        status=StepExecutionStatus.BLOCKED,
        error="Prerequisite failed",
    )

    agg = MultiStepExecutionResult(
        plan_id="req-123",
        status=MultiStepExecutionStatus.PARTIAL_SUCCESS,
        step_results={"step_1": res1, "step_2": res2, "step_3": res3},
        overall_answer="Step 1 succeeded, but step 2 failed.",
        warnings=[],
        error="Step 2 failed",
    )

    assert not agg.is_all_succeeded
    assert agg.has_failures
    assert agg.has_blocked
    assert agg.get_step_result("step_1") == res1
    assert agg.get_step_result("step_2") == res2
    assert agg.get_step_result("step_99") is None


def test_step_output_reference_parsing():
    """Verify parsing from dictionary with standard '$step_ref' key."""
    ref_dict = {"$step_ref": "step_task", "field": "task_id", "expected_type": "str"}
    assert StepOutputReference.is_reference(ref_dict)
    ref = StepOutputReference.from_dict(ref_dict)
    assert ref.step_ref == "step_task"
    assert ref.field == "task_id"
    assert ref.expected_type == "str"

    # Default field and expected_type
    ref_minimal = StepOutputReference.from_dict({"$step_ref": "step_task"})
    assert ref_minimal.field == "entity_id"
    assert ref_minimal.expected_type == "str"


def test_output_reference_successful_resolution():
    """Verify resolving references across primitive types (str, int, float, bool)."""
    step_results = {
        "step_1": StepExecutionResult(
            step_id="step_1",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.SUCCEEDED,
            entity_id="TASK-88",
            output_fields={
                "task_id": "TASK-88",
                "count": 42,
                "score": 98.6,
                "is_urgent": True,
            },
        )
    }

    current_step = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["step_1"],
    )

    # String reference
    ref_str = StepOutputReference(step_ref="step_1", field="task_id", expected_type="str")
    assert ref_str.validate_and_resolve(current_step, step_results) == "TASK-88"

    # Default entity_id field
    ref_entity = StepOutputReference(step_ref="step_1", field="entity_id", expected_type="str")
    assert ref_entity.validate_and_resolve(current_step, step_results) == "TASK-88"

    # Integer reference
    ref_int = StepOutputReference(step_ref="step_1", field="count", expected_type="int")
    assert ref_int.validate_and_resolve(current_step, step_results) == 42

    # Float/number reference
    ref_float = StepOutputReference(step_ref="step_1", field="score", expected_type="float")
    assert ref_float.validate_and_resolve(current_step, step_results) == 98.6

    # Boolean reference
    ref_bool = StepOutputReference(step_ref="step_1", field="is_urgent", expected_type="bool")
    assert ref_bool.validate_and_resolve(current_step, step_results) is True


def test_output_reference_rejects_undeclared_dependency():
    """Verify reference is rejected if source step is not in current step's dependencies."""
    step_results = {
        "step_1": StepExecutionResult(
            step_id="step_1",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.SUCCEEDED,
            entity_id="TASK-1",
        )
    }

    current_step = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=[],  # step_1 is NOT declared!
    )

    ref = StepOutputReference(step_ref="step_1", field="entity_id", expected_type="str")
    with pytest.raises(UndeclaredDependencyReferenceError, match="not declared in dependencies"):
        ref.validate_and_resolve(current_step, step_results)


def test_output_reference_rejects_missing_source_step():
    """Verify reference is rejected if source step is not found in results."""
    step_results = {}
    current_step = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["step_1"],
    )

    ref = StepOutputReference(step_ref="step_1", field="entity_id", expected_type="str")
    with pytest.raises(SourceStepNotFoundError, match="was not found in executed results"):
        ref.validate_and_resolve(current_step, step_results)


def test_output_reference_rejects_failed_or_blocked_source_step():
    """Verify reference is rejected if source step did not succeed."""
    step_results = {
        "step_1": StepExecutionResult(
            step_id="step_1",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.FAILED,
            error="DB error",
        )
    }
    current_step = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["step_1"],
    )

    ref = StepOutputReference(step_ref="step_1", field="entity_id", expected_type="str")
    with pytest.raises(SourceStepNotSucceededError, match="did not succeed \\(status: failed\\)"):
        ref.validate_and_resolve(current_step, step_results)


def test_output_reference_rejects_missing_output_field():
    """Verify reference is rejected if requested field does not exist."""
    step_results = {
        "step_1": StepExecutionResult(
            step_id="step_1",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.SUCCEEDED,
            entity_id="TASK-1",
            output_fields={"task_id": "TASK-1"},
        )
    }
    current_step = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["step_1"],
    )

    ref = StepOutputReference(step_ref="step_1", field="missing_field", expected_type="str")
    with pytest.raises(OutputFieldNotFoundError, match="does not contain field 'missing_field'"):
        ref.validate_and_resolve(current_step, step_results)


def test_output_reference_rejects_empty_output_value():
    """Verify reference is rejected if value is an empty string."""
    step_results = {
        "step_1": StepExecutionResult(
            step_id="step_1",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.SUCCEEDED,
            entity_id="   ",
            output_fields={"empty_val": "   "},
        )
    }
    current_step = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["step_1"],
    )

    ref = StepOutputReference(step_ref="step_1", field="empty_val", expected_type="str")
    with pytest.raises(EmptyOutputValueError, match="is an empty string"):
        ref.validate_and_resolve(current_step, step_results)


def test_output_reference_rejects_type_mismatch():
    """Verify reference strictly validates expected primitive types."""
    step_results = {
        "step_1": StepExecutionResult(
            step_id="step_1",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.SUCCEEDED,
            output_fields={
                "str_val": "hello",
                "bool_val": True,
                "int_val": 42,
            },
        )
    }
    current_step = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["step_1"],
    )

    # Boolean masquerading as int: bool is a subclass of int in Python, but should be rejected here
    ref_int_mismatch = StepOutputReference(step_ref="step_1", field="bool_val", expected_type="int")
    with pytest.raises(OutputTypeMismatchError, match="expected integer, got bool"):
        ref_int_mismatch.validate_and_resolve(current_step, step_results)

    # String where int is expected
    ref_int_str = StepOutputReference(step_ref="step_1", field="str_val", expected_type="int")
    with pytest.raises(OutputTypeMismatchError, match="expected integer, got str"):
        ref_int_str.validate_and_resolve(current_step, step_results)

    # Int where bool is expected
    ref_bool_mismatch = StepOutputReference(step_ref="step_1", field="int_val", expected_type="bool")
    with pytest.raises(OutputTypeMismatchError, match="expected boolean, got int"):
        ref_bool_mismatch.validate_and_resolve(current_step, step_results)

    # Unsupported expected type
    ref_bad_type = StepOutputReference(step_ref="step_1", field="str_val", expected_type="custom_class")
    with pytest.raises(ValueError, match="Unsupported expected_type 'custom_class'"):
        ref_bad_type.validate_and_resolve(current_step, step_results)


def test_resolve_step_parameters_function():
    """Verify resolve_step_parameters resolves reference dicts while preserving literals."""
    step_results = {
        "step_task": StepExecutionResult(
            step_id="step_task",
            agent=TargetAgent.OPERATIONS_AGENT,
            action="create_task",
            status=StepExecutionStatus.SUCCEEDED,
            entity_id="TASK-99",
            output_fields={"task_id": "TASK-99"},
        )
    }

    step = ExecutionStep(
        step_id="step_cal",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["step_task"],
        parameters={
            "title": "Review Task",
            "task_id": {"$step_ref": "step_task", "field": "task_id", "expected_type": "str"},
            "duration": 30,
        },
    )

    resolved = resolve_step_parameters(step, step_results)
    assert resolved == {
        "title": "Review Task",
        "task_id": "TASK-99",
        "duration": 30,
    }


def test_no_arbitrary_code_or_expression_evaluation():
    """Verify parameters containing Python expressions or templates are not evaluated."""
    step = ExecutionStep(
        step_id="step_cal",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        parameters={
            "eval_expr": "__import__('os').system('echo hack')",
            "template_str": "${step_task.task_id}",
            "regular_dict": {"not_a_step_ref": 123},
        },
    )

    resolved = resolve_step_parameters(step, {})
    # Untouched, not evaluated
    assert resolved["eval_expr"] == "__import__('os').system('echo hack')"
    assert resolved["template_str"] == "${step_task.task_id}"
    assert resolved["regular_dict"] == {"not_a_step_ref": 123}
