"""
Unit tests for Stage B5.2: MultiStepCoordinator.

Covers topological execution ordering, failure blocking, transitive blocking,
safe branch continuation, output reference propagation, and aggregate statuses.
"""

from typing import Any
import pytest

from application.cognitive.multi_step_coordinator import (
    MultiStepCoordinator,
    PlanDependencyError,
    StepExecutor,
)
from domain.reasoning.value_objects import (
    ActionType,
    CognitivePlan,
    ExecutionStep,
    IntentCategory,
    MultiStepExecutionResult,
    MultiStepExecutionStatus,
    StepExecutionResult,
    StepExecutionStatus,
    TargetAgent,
)


def _make_plan(steps: list[ExecutionStep], request_id: str = "req-test") -> CognitivePlan:
    """Helper to construct a CognitivePlan with the given steps."""
    return CognitivePlan(
        request_id=request_id,
        original_message="Test plan",
        intent=IntentCategory.TASK_ACTION,
        execution_steps=steps,
    )


def test_single_step_execution():
    """1. Single-step execution succeeds and returns ALL_SUCCEEDED."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
            entity_id="task-1",
            output_fields={"task_id": "task-1"},
            answer="Created task task-1.",
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    step = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task")
    plan = _make_plan([step])

    result = coordinator.execute(plan)

    assert invocations == ["s1"]
    assert result.status == MultiStepExecutionStatus.ALL_SUCCEEDED
    assert result.is_all_succeeded
    assert "s1" in result.step_results
    assert result.step_results["s1"].status == StepExecutionStatus.SUCCEEDED


def test_two_step_sequential_dependency():
    """2. Two-step sequential dependency: s1 executes before s2."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
            entity_id=f"id-{step.step_id}",
            output_fields={"id": f"id-{step.step_id}"},
            answer=f"Step {step.step_id} succeeded.",
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="schedule", dependencies=["s1"])
    plan = _make_plan([s1, s2])

    result = coordinator.execute(plan)

    assert invocations == ["s1", "s2"]
    assert result.status == MultiStepExecutionStatus.ALL_SUCCEEDED


def test_three_step_dependency_chain():
    """3. Three-step dependency chain (s1 -> s2 -> s3) passes outputs down the chain."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append((step.step_id, params))
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
            entity_id=f"id-{step.step_id}",
            output_fields={"entity_id": f"id-{step.step_id}"},
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task")
    s2 = ExecutionStep(
        step_id="s2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
        dependencies=["s1"],
        parameters={"task_ref": {"$step_ref": "s1", "field": "entity_id"}},
    )
    s3 = ExecutionStep(
        step_id="s3",
        agent=TargetAgent.REMINDER_SERVICE,
        action="remind",
        dependencies=["s2"],
        parameters={"cal_ref": {"$step_ref": "s2", "field": "entity_id"}},
    )
    plan = _make_plan([s1, s2, s3])

    result = coordinator.execute(plan)

    assert [inv[0] for inv in invocations] == ["s1", "s2", "s3"]
    assert invocations[1][1]["task_ref"] == "id-s1"
    assert invocations[2][1]["cal_ref"] == "id-s2"
    assert result.status == MultiStepExecutionStatus.ALL_SUCCEEDED


def test_independent_steps_preserve_deterministic_original_order():
    """4. Independent steps execute in their exact original plan order."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    # Order in plan: beta, alpha, gamma
    s_beta = ExecutionStep(step_id="beta", agent=TargetAgent.OPERATIONS_AGENT, action="act_b")
    s_alpha = ExecutionStep(step_id="alpha", agent=TargetAgent.CALENDAR_AGENT, action="act_a")
    s_gamma = ExecutionStep(step_id="gamma", agent=TargetAgent.GOVERNANCE_AGENT, action="act_g")
    plan = _make_plan([s_beta, s_alpha, s_gamma])

    coordinator.execute(plan)

    assert invocations == ["beta", "alpha", "gamma"]


def test_mixed_independent_and_dependent_branches():
    """5. Mixed independent and dependent branches execute deterministically."""
    # Branch 1: b1_1 -> b1_2
    # Branch 2: b2_1 (independent)
    # Plan order: b1_1, b2_1, b1_2
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    b1_1 = ExecutionStep(step_id="b1_1", agent=TargetAgent.OPERATIONS_AGENT, action="act")
    b2_1 = ExecutionStep(step_id="b2_1", agent=TargetAgent.CALENDAR_AGENT, action="act")
    b1_2 = ExecutionStep(step_id="b1_2", agent=TargetAgent.OPERATIONS_AGENT, action="act", dependencies=["b1_1"])
    plan = _make_plan([b1_1, b2_1, b1_2])

    coordinator.execute(plan)

    # At start, b1_1 and b2_1 are ready. b1_1 runs first (index 0).
    # Then b2_1 (index 1) and b1_2 (index 2) are ready; b2_1 runs next because index 1 < 2.
    # Then b1_2 runs.
    assert invocations == ["b1_1", "b2_1", "b1_2"]


def test_duplicate_step_ids_rejected_before_execution():
    """6. Duplicate step IDs are rejected before any step executes."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="dup_id", agent=TargetAgent.OPERATIONS_AGENT, action="act1")
    s2 = ExecutionStep(step_id="dup_id", agent=TargetAgent.CALENDAR_AGENT, action="act2")

    # Using object with duplicate IDs bypasses CognitivePlan pydantic check if constructed manually
    # or validate_plan_graph directly
    plan = CognitivePlan.model_construct(
        request_id="req-dup",
        original_message="test",
        intent=IntentCategory.TASK_ACTION,
        execution_steps=[s1, s2],
    )

    with pytest.raises((PlanDependencyError, ValueError), match="Duplicate step_id 'dup_id'"):
        coordinator.execute(plan)

    assert invocations == []


def test_unknown_dependency_rejected_before_execution():
    """7. Unknown dependency rejected before execution."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="act", dependencies=["ghost_step"])
    plan = CognitivePlan.model_construct(
        request_id="req-unknown",
        original_message="test",
        intent=IntentCategory.TASK_ACTION,
        execution_steps=[s1],
    )

    with pytest.raises((PlanDependencyError, ValueError), match="unknown dependency 'ghost_step'"):
        coordinator.execute(plan)

    assert invocations == []


def test_self_dependency_rejected_before_execution():
    """8. Self-dependency rejected before execution."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="act", dependencies=["s1"])
    plan = CognitivePlan.model_construct(
        request_id="req-self",
        original_message="test",
        intent=IntentCategory.TASK_ACTION,
        execution_steps=[s1],
    )

    with pytest.raises((PlanDependencyError, ValueError), match="cannot depend on itself"):
        coordinator.execute(plan)

    assert invocations == []


def test_dependency_cycle_rejected_before_execution():
    """9. Dependency cycle rejected before execution."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="act", dependencies=["s2"])
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.OPERATIONS_AGENT, action="act", dependencies=["s1"])
    plan = CognitivePlan.model_construct(
        request_id="req-cycle",
        original_message="test",
        intent=IntentCategory.TASK_ACTION,
        execution_steps=[s1, s2],
    )

    with pytest.raises((PlanDependencyError, ValueError), match="Dependency cycle detected"):
        coordinator.execute(plan)

    assert invocations == []


def test_successful_prerequisite_permits_dependent_execution():
    """10. Successful prerequisite permits dependent execution."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="link", dependencies=["s1"])
    plan = _make_plan([s1, s2])

    result = coordinator.execute(plan)

    assert invocations == ["s1", "s2"]
    assert result.step_results["s2"].status == StepExecutionStatus.SUCCEEDED


def test_failed_prerequisite_blocks_direct_dependent():
    """11. Failed prerequisite blocks direct dependent from running."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        if step.step_id == "s1":
            return StepExecutionResult(
                step_id="s1",
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Database constraint error",
            )
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=StepExecutionStatus.SUCCEEDED)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="link", dependencies=["s1"])
    plan = _make_plan([s1, s2])

    result = coordinator.execute(plan)

    assert invocations == ["s1"]
    assert result.step_results["s1"].status == StepExecutionStatus.FAILED
    assert result.step_results["s2"].status == StepExecutionStatus.BLOCKED
    assert "did not succeed" in (result.step_results["s2"].error or "")


def test_failed_prerequisite_blocks_transitive_dependent():
    """12. Failed prerequisite blocks transitive dependents across multiple steps."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.FAILED if step.step_id == "s1" else StepExecutionStatus.SUCCEEDED,
            error="s1 failed" if step.step_id == "s1" else None,
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a1")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="a2", dependencies=["s1"])
    s3 = ExecutionStep(step_id="s3", agent=TargetAgent.REMINDER_SERVICE, action="a3", dependencies=["s2"])
    plan = _make_plan([s1, s2, s3])

    result = coordinator.execute(plan)

    assert invocations == ["s1"]
    assert result.step_results["s1"].status == StepExecutionStatus.FAILED
    assert result.step_results["s2"].status == StepExecutionStatus.BLOCKED
    assert result.step_results["s3"].status == StepExecutionStatus.BLOCKED


def test_independent_safe_branch_continues_after_another_branch_fails():
    """13. Independent safe branch continues even after another branch fails."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        if step.step_id == "branch1_a":
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Branch 1 failed",
            )
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    # Branch 1: branch1_a (fails) -> branch1_b (should be blocked)
    # Branch 2: branch2_a (succeeds) -> branch2_b (should succeed)
    b1_a = ExecutionStep(step_id="branch1_a", agent=TargetAgent.OPERATIONS_AGENT, action="a")
    b1_b = ExecutionStep(step_id="branch1_b", agent=TargetAgent.OPERATIONS_AGENT, action="b", dependencies=["branch1_a"])
    b2_a = ExecutionStep(step_id="branch2_a", agent=TargetAgent.CALENDAR_AGENT, action="a")
    b2_b = ExecutionStep(step_id="branch2_b", agent=TargetAgent.CALENDAR_AGENT, action="b", dependencies=["branch2_a"])
    plan = _make_plan([b1_a, b2_a, b1_b, b2_b])

    result = coordinator.execute(plan)

    assert "branch1_a" in invocations
    assert "branch2_a" in invocations
    assert "branch2_b" in invocations
    assert "branch1_b" not in invocations
    assert result.step_results["branch1_b"].status == StepExecutionStatus.BLOCKED
    assert result.step_results["branch2_b"].status == StepExecutionStatus.SUCCEEDED
    assert result.status == MultiStepExecutionStatus.PARTIAL_SUCCESS


def test_blocked_step_does_not_satisfy_another_dependency():
    """14. Blocked step does not satisfy another dependency."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.FAILED,
            error="fail",
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="b", dependencies=["s1"])
    s3 = ExecutionStep(step_id="s3", agent=TargetAgent.GOVERNANCE_AGENT, action="c", dependencies=["s2"])
    plan = _make_plan([s1, s2, s3])

    result = coordinator.execute(plan)

    assert result.step_results["s2"].status == StepExecutionStatus.BLOCKED
    assert result.step_results["s3"].status == StepExecutionStatus.BLOCKED
    assert invocations == ["s1"]


def test_skipped_step_does_not_satisfy_another_dependency():
    """15. Skipped step does not satisfy another dependency."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SKIPPED,
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="b", dependencies=["s1"])
    plan = _make_plan([s1, s2])

    result = coordinator.execute(plan)

    assert invocations == ["s1"]
    assert result.step_results["s1"].status == StepExecutionStatus.SKIPPED
    assert result.step_results["s2"].status == StepExecutionStatus.BLOCKED


def test_failed_parameter_reference_does_not_invoke_executor():
    """16. Failed parameter reference marks step failed/blocked and does not invoke executor."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
            output_fields={"other_field": "val"},
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create")
    s2 = ExecutionStep(
        step_id="s2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="link",
        dependencies=["s1"],
        parameters={"id": {"$step_ref": "s1", "field": "nonexistent_field"}},
    )
    plan = _make_plan([s1, s2])

    result = coordinator.execute(plan)

    assert invocations == ["s1"]  # s2 executor NEVER called!
    assert result.step_results["s2"].status == StepExecutionStatus.FAILED
    assert "does not contain field 'nonexistent_field'" in (result.step_results["s2"].error or "")


def test_invalid_output_type_does_not_invoke_executor():
    """17. Output type mismatch does not invoke executor."""
    invocations = []

    def executor(step, plan, params, prereqs):
        invocations.append(step.step_id)
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
            output_fields={"task_id": "not-an-int"},
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create")
    s2 = ExecutionStep(
        step_id="s2",
        agent=TargetAgent.CALENDAR_AGENT,
        action="link",
        dependencies=["s1"],
        parameters={"count": {"$step_ref": "s1", "field": "task_id", "expected_type": "int"}},
    )
    plan = _make_plan([s1, s2])

    result = coordinator.execute(plan)

    assert invocations == ["s1"]
    assert result.step_results["s2"].status == StepExecutionStatus.FAILED
    assert "expected integer" in (result.step_results["s2"].error or "")


def test_executor_exception_becomes_controlled_step_failure():
    """18. Executor raising an unhandled exception becomes a controlled step failure."""
    def executor(step, plan, params, prereqs):
        if step.step_id == "s1":
            raise RuntimeError("Database connection pool exhausted")
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=StepExecutionStatus.SUCCEEDED)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="act")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="act", dependencies=["s1"])
    plan = _make_plan([s1, s2])

    result = coordinator.execute(plan)

    assert result.step_results["s1"].status == StepExecutionStatus.FAILED
    assert "Database connection pool exhausted" in (result.step_results["s1"].error or "")
    assert result.step_results["s2"].status == StepExecutionStatus.BLOCKED


def test_invalid_executor_result_is_rejected():
    """19. Invalid executor return value is handled as a controlled failure."""
    def executor(step, plan, params, prereqs):
        # Returns invalid result with wrong step_id
        return StepExecutionResult(step_id="wrong_id", agent=step.agent, action=step.action, status=StepExecutionStatus.SUCCEEDED)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="act")
    plan = _make_plan([s1])

    result = coordinator.execute(plan)

    assert result.step_results["s1"].status == StepExecutionStatus.FAILED
    assert "invalid result contract" in (result.step_results["s1"].error or "")


def test_every_plan_step_appears_in_final_result():
    """20. Every step in the plan receives an explicit result in step_results."""
    def executor(step, plan, params, prereqs):
        if step.step_id == "s1":
            return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=StepExecutionStatus.FAILED)
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=StepExecutionStatus.SUCCEEDED)

    coordinator = MultiStepCoordinator(step_executor=executor)
    s1 = ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a")
    s2 = ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="b", dependencies=["s1"])
    s3 = ExecutionStep(step_id="s3", agent=TargetAgent.REMINDER_SERVICE, action="c", dependencies=["s2"])
    s4 = ExecutionStep(step_id="s4", agent=TargetAgent.KNOWLEDGE_AGENT, action="d")
    plan = _make_plan([s1, s2, s3, s4])

    result = coordinator.execute(plan)

    assert set(result.step_results.keys()) == {"s1", "s2", "s3", "s4"}
    assert result.step_results["s1"].status == StepExecutionStatus.FAILED
    assert result.step_results["s2"].status == StepExecutionStatus.BLOCKED
    assert result.step_results["s3"].status == StepExecutionStatus.BLOCKED
    assert result.step_results["s4"].status == StepExecutionStatus.SUCCEEDED


def test_aggregate_all_succeeded_behavior():
    """21. When all steps succeed, aggregate status is ALL_SUCCEEDED."""
    def executor(step, plan, params, prereqs):
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=StepExecutionStatus.SUCCEEDED)

    coordinator = MultiStepCoordinator(step_executor=executor)
    plan = _make_plan([
        ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a"),
        ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="b"),
    ])

    result = coordinator.execute(plan)
    assert result.status == MultiStepExecutionStatus.ALL_SUCCEEDED
    assert result.is_all_succeeded
    assert not result.has_failures
    assert not result.has_blocked


def test_aggregate_partial_success_behavior():
    """22. When some steps succeed and some fail, aggregate status is PARTIAL_SUCCESS."""
    def executor(step, plan, params, prereqs):
        status = StepExecutionStatus.SUCCEEDED if step.step_id == "s1" else StepExecutionStatus.FAILED
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=status)

    coordinator = MultiStepCoordinator(step_executor=executor)
    plan = _make_plan([
        ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a"),
        ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="b"),
    ])

    result = coordinator.execute(plan)
    assert result.status == MultiStepExecutionStatus.PARTIAL_SUCCESS
    assert not result.is_all_succeeded
    assert result.has_failures


def test_aggregate_failed_behavior():
    """23. When first step fails without any successes, aggregate status is FAILED."""
    def executor(step, plan, params, prereqs):
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=StepExecutionStatus.FAILED, error="fail")

    coordinator = MultiStepCoordinator(step_executor=executor)
    plan = _make_plan([
        ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a"),
        ExecutionStep(step_id="s2", agent=TargetAgent.CALENDAR_AGENT, action="b", dependencies=["s1"]),
    ])

    result = coordinator.execute(plan)
    assert result.status == MultiStepExecutionStatus.FAILED
    assert not result.is_all_succeeded
    assert result.has_failures
    assert result.has_blocked


def test_aggregate_blocked_behavior():
    """24. When all steps are blocked without any executing successfully, aggregate status is BLOCKED."""
    coordinator = MultiStepCoordinator(step_executor=lambda *args: None)
    # Step depends on s1, but s1 output is missing / unavailable
    s1 = ExecutionStep(
        step_id="s1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="a",
        dependencies=[],
        parameters={"ref": {"$step_ref": "s_prereq", "field": "id"}},  # undeclared dependency reference inside parameters
    )
    # Notice: s_prereq is not in dependencies, so resolve_step_parameters raises UndeclaredDependencyReferenceError -> FAILED
    # Let's test BLOCKED aggregate: when a step parameter references a source step that was blocked or not succeeded
    # If all steps ended in BLOCKED:
    def fake_executor_blocked(step, plan, params, prereqs):
        return StepExecutionResult(step_id=step.step_id, agent=step.agent, action=step.action, status=StepExecutionStatus.BLOCKED, error="unavailable")

    coord = MultiStepCoordinator(step_executor=fake_executor_blocked)
    plan = _make_plan([ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="a")])
    result = coord.execute(plan)
    assert result.status == MultiStepExecutionStatus.BLOCKED
    assert result.has_blocked
    assert not result.has_failures


def test_clarification_required_aggregation():
    """25. When executor explicitly returns clarification required, aggregate status is CLARIFICATION_REQUIRED."""
    def executor(step, plan, params, prereqs):
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action="clarify",
            status=StepExecutionStatus.PENDING,
            output_fields={"requires_clarification": True},
            answer="Please clarify the time for the meeting.",
        )

    coordinator = MultiStepCoordinator(step_executor=executor)
    plan = _make_plan([ExecutionStep(step_id="s1", agent=TargetAgent.CALENDAR_AGENT, action="clarify")])

    result = coordinator.execute(plan)
    assert result.status == MultiStepExecutionStatus.CLARIFICATION_REQUIRED
    assert "clarify" in result.overall_answer.lower()
