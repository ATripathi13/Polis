"""
Deterministic, dependency-aware execution coordinator for multi-step CognitivePlans.

Orchestrates multi-step plans according to declared dependencies using Kahn's algorithm,
preserves original plan ordering among simultaneously executable steps, resolves structured
output references, and propagates failures to direct and transitive dependents.
"""

import logging
from typing import Any, Callable, Protocol

from domain.reasoning.value_objects import (
    CognitivePlan,
    ExecutionStep,
    MultiStepExecutionResult,
    MultiStepExecutionStatus,
    OutputReferenceError,
    SourceStepNotFoundError,
    SourceStepNotSucceededError,
    StepExecutionResult,
    StepExecutionStatus,
    resolve_step_parameters,
)

logger = logging.getLogger(__name__)


class StepExecutor(Protocol):
    """
    Protocol for specialist step execution callbacks.
    """
    def __call__(
        self,
        step: ExecutionStep,
        plan: CognitivePlan,
        resolved_parameters: dict[str, Any],
        prerequisite_results: dict[str, StepExecutionResult],
    ) -> StepExecutionResult:
        ...


class PlanDependencyError(ValueError):
    """Raised when a plan has invalid, duplicate, missing, or cyclic dependencies."""
    pass


class MultiStepCoordinator:
    """
    Deterministic execution coordinator for multi-step CognitivePlans.
    """

    def __init__(self, step_executor: StepExecutor | None = None) -> None:
        self._default_executor = step_executor

    @staticmethod
    def validate_plan_graph(plan: CognitivePlan) -> None:
        """
        Validate plan graph invariants before any mutation occurs:
        1. Unique step IDs.
        2. No self-dependencies.
        3. All dependencies exist in the plan.
        4. No dependency cycles (via DFS).
        """
        seen_step_ids: set[str] = set()
        for s in plan.execution_steps:
            if s.step_id in seen_step_ids:
                raise PlanDependencyError(
                    f"Duplicate step_id '{s.step_id}' found in execution steps."
                )
            seen_step_ids.add(s.step_id)

        step_ids = seen_step_ids

        # Self-dependency & unknown dependency checks
        for step in plan.execution_steps:
            for dep in step.dependencies:
                if dep == step.step_id:
                    raise PlanDependencyError(
                        f"Step '{step.step_id}' cannot depend on itself."
                    )
                if dep not in step_ids:
                    raise PlanDependencyError(
                        f"Step '{step.step_id}' references unknown dependency '{dep}'."
                    )

        # Cycle detection via DFS
        adj: dict[str, list[str]] = {s.step_id: s.dependencies for s in plan.execution_steps}
        visited: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

        def dfs(node: str) -> bool:
            visited[node] = 1
            for neighbour in adj.get(node, []):
                state = visited.get(neighbour, 0)
                if state == 1:
                    return True
                if state == 0 and dfs(neighbour):
                    return True
            visited[node] = 2
            return False

        for sid in step_ids:
            if visited.get(sid, 0) == 0:
                if dfs(sid):
                    raise PlanDependencyError(
                        f"Dependency cycle detected in execution steps including '{sid}'."
                    )

    def execute(
        self,
        plan: CognitivePlan,
        step_executor: StepExecutor | None = None,
        initial_step_results: dict[str, StepExecutionResult] | None = None,
    ) -> MultiStepExecutionResult:
        """
        Execute a multi-step plan deterministically according to declared dependencies.
        Supports safe resumption from prior successful step results without repeating completed mutations.
        """
        executor = step_executor or self._default_executor
        if executor is None:
            raise ValueError("No step_executor provided for plan execution.")

        # 1. Graph validation before any step executes
        self.validate_plan_graph(plan)

        # Handle empty plan
        if not plan.execution_steps:
            return MultiStepExecutionResult(
                plan_id=plan.request_id,
                status=MultiStepExecutionStatus.ALL_SUCCEEDED,
                step_results={},
                overall_answer="No execution steps required.",
            )

        step_map: dict[str, ExecutionStep] = {s.step_id: s for s in plan.execution_steps}
        original_indices: dict[str, int] = {s.step_id: idx for idx, s in enumerate(plan.execution_steps)}

        # Build dependency graph
        dependents: dict[str, list[str]] = {s.step_id: [] for s in plan.execution_steps}
        for s in plan.execution_steps:
            for dep in s.dependencies:
                dependents[dep].append(s.step_id)

        # Helper to find all transitive dependents of a step (in deterministic plan order)
        def get_transitive_dependents(root_step_id: str) -> list[str]:
            descendants: list[str] = []
            queue = list(dependents.get(root_step_id, []))
            visited_desc: set[str] = set()
            while queue:
                current_desc = queue.pop(0)
                if current_desc not in visited_desc:
                    visited_desc.add(current_desc)
                    descendants.append(current_desc)
                    queue.extend(dependents.get(current_desc, []))
            descendants.sort(key=lambda sid: original_indices[sid])
            return descendants

        step_results: dict[str, StepExecutionResult] = dict(initial_step_results or {})
        successful_results: dict[str, StepExecutionResult] = {
            sid: res for sid, res in step_results.items()
            if res.status == StepExecutionStatus.SUCCEEDED
        }

        # Interrupted RUNNING steps: fail-closed without blind retry
        for sid, res in list(step_results.items()):
            if res.status == StepExecutionStatus.RUNNING:
                logger.warning(
                    "Step '%s' was recorded in RUNNING state from prior execution. Refusing blind retry.",
                    sid,
                )
                step_results[sid] = StepExecutionResult(
                    step_id=sid,
                    agent=res.agent,
                    action=res.action,
                    status=StepExecutionStatus.FAILED,
                    error="Interrupted execution: step was left in RUNNING state (uncertain outcome) without confirmed result. Refusing blind retry.",
                    answer="⚠️ Operation was interrupted in an uncertain state and cannot be safely retried.",
                )
                for desc_id in get_transitive_dependents(sid):
                    if desc_id not in step_results:
                        desc_step = step_map[desc_id]
                        step_results[desc_id] = StepExecutionResult(
                            step_id=desc_id,
                            agent=desc_step.agent,
                            action=desc_step.action,
                            status=StepExecutionStatus.BLOCKED,
                            error=f"Prerequisite step '{sid}' was in an uncertain/interrupted state.",
                        )

        # Non-succeeded initial results: block dependents
        for sid, res in list(step_results.items()):
            if res.status in (StepExecutionStatus.FAILED, StepExecutionStatus.BLOCKED):
                for desc_id in get_transitive_dependents(sid):
                    if desc_id not in step_results:
                        desc_step = step_map[desc_id]
                        step_results[desc_id] = StepExecutionResult(
                            step_id=desc_id,
                            agent=desc_step.agent,
                            action=desc_step.action,
                            status=StepExecutionStatus.BLOCKED,
                            error=f"Prerequisite step '{sid}' was {res.status.value}.",
                        )

        # Build in-degrees (count of prerequisites that have not yet succeeded)
        in_degree: dict[str, int] = {}
        for s in plan.execution_steps:
            if s.step_id in successful_results or (s.step_id in step_results and step_results[s.step_id].status != StepExecutionStatus.PENDING):
                in_degree[s.step_id] = 999999  # Already completed/handled, do not queue
            else:
                in_degree[s.step_id] = sum(1 for dep in s.dependencies if dep not in successful_results)

        # Initial ready steps (in-degree == 0, not yet succeeded, not failed/blocked)
        ready_step_ids: list[str] = [
            s.step_id for s in plan.execution_steps
            if in_degree[s.step_id] == 0
            and s.step_id not in successful_results
            and (s.step_id not in step_results or step_results[s.step_id].status == StepExecutionStatus.PENDING)
        ]
        ready_step_ids.sort(key=lambda sid: original_indices[sid])

        while ready_step_ids:
            current_step_id = ready_step_ids.pop(0)
            current_step = step_map[current_step_id]

            logger.debug("Executing step '%s' (agent: %s, action: %s)", current_step_id, current_step.agent, current_step.action)

            # 1. Parameter resolution using successful prerequisite results
            try:
                resolved_parameters = resolve_step_parameters(current_step, successful_results)
            except (SourceStepNotSucceededError, SourceStepNotFoundError) as exc:
                # Prerequisite output unavailable -> step is BLOCKED
                err_msg = f"Prerequisite output unavailable: {exc}"
                logger.warning("Step '%s' blocked: %s", current_step_id, err_msg)
                res = StepExecutionResult(
                    step_id=current_step_id,
                    agent=current_step.agent,
                    action=current_step.action,
                    status=StepExecutionStatus.BLOCKED,
                    error=err_msg,
                )
                step_results[current_step_id] = res

                # Block all direct and transitive dependents
                for desc_id in get_transitive_dependents(current_step_id):
                    if desc_id not in step_results:
                        desc_step = step_map[desc_id]
                        step_results[desc_id] = StepExecutionResult(
                            step_id=desc_id,
                            agent=desc_step.agent,
                            action=desc_step.action,
                            status=StepExecutionStatus.BLOCKED,
                            error=f"Prerequisite step '{current_step_id}' was blocked.",
                        )
                        if desc_id in ready_step_ids:
                            ready_step_ids.remove(desc_id)
                continue

            except (OutputReferenceError, ValueError) as exc:
                # Reference declaration / type mismatch error -> step is FAILED
                err_msg = f"Parameter reference error: {exc}"
                logger.warning("Step '%s' failed parameter resolution: %s", current_step_id, err_msg)
                res = StepExecutionResult(
                    step_id=current_step_id,
                    agent=current_step.agent,
                    action=current_step.action,
                    status=StepExecutionStatus.FAILED,
                    error=err_msg,
                )
                step_results[current_step_id] = res

                # Block all direct and transitive dependents
                for desc_id in get_transitive_dependents(current_step_id):
                    if desc_id not in step_results:
                        desc_step = step_map[desc_id]
                        step_results[desc_id] = StepExecutionResult(
                            step_id=desc_id,
                            agent=desc_step.agent,
                            action=desc_step.action,
                            status=StepExecutionStatus.BLOCKED,
                            error=f"Prerequisite step '{current_step_id}' failed parameter resolution.",
                        )
                        if desc_id in ready_step_ids:
                            ready_step_ids.remove(desc_id)
                continue

            # 2. Invoke executor callback
            try:
                step_result = executor(
                    current_step,
                    plan,
                    resolved_parameters,
                    dict(successful_results),
                )
            except Exception as exc:
                logger.exception("Executor raised exception for step '%s': %s", current_step_id, exc)
                step_result = StepExecutionResult(
                    step_id=current_step_id,
                    agent=current_step.agent,
                    action=current_step.action,
                    status=StepExecutionStatus.FAILED,
                    error=f"Executor raised unhandled exception: {exc}",
                )

            # 3. Validate executor result contract
            if not isinstance(step_result, StepExecutionResult) or step_result.step_id != current_step_id:
                logger.error(
                    "Invalid executor result for step '%s': got %r",
                    current_step_id,
                    step_result,
                )
                step_result = StepExecutionResult(
                    step_id=current_step_id,
                    agent=current_step.agent,
                    action=current_step.action,
                    status=StepExecutionStatus.FAILED,
                    error=f"Executor returned invalid result contract for step '{current_step_id}'.",
                )

            step_results[current_step_id] = step_result

            # 4. Handle step outcome
            if step_result.status == StepExecutionStatus.SUCCEEDED:
                successful_results[current_step_id] = step_result

                # Check dependent steps
                for dep_id in dependents[current_step_id]:
                    if dep_id not in step_results or step_results[dep_id].status == StepExecutionStatus.PENDING:
                        in_degree[dep_id] -= 1
                        if in_degree[dep_id] == 0:
                            if dep_id not in ready_step_ids:
                                ready_step_ids.append(dep_id)
                            # Deterministic order preservation
                            ready_step_ids.sort(key=lambda sid: original_indices[sid])
            else:
                # Step failed, was blocked, or skipped
                logger.warning(
                    "Step '%s' ended with status '%s'. Blocking dependents.",
                    current_step_id,
                    step_result.status.value,
                )
                for desc_id in get_transitive_dependents(current_step_id):
                    if desc_id not in step_results:
                        desc_step = step_map[desc_id]
                        step_results[desc_id] = StepExecutionResult(
                            step_id=desc_id,
                            agent=desc_step.agent,
                            action=desc_step.action,
                            status=StepExecutionStatus.BLOCKED,
                            error=f"Prerequisite step '{current_step_id}' did not succeed (status: {step_result.status.value}).",
                        )
                        if desc_id in ready_step_ids:
                            ready_step_ids.remove(desc_id)

        # 5. Post-loop reconciliation: ensure all plan steps receive an explicit result status
        for s in plan.execution_steps:
            if s.step_id not in step_results:
                step_results[s.step_id] = StepExecutionResult(
                    step_id=s.step_id,
                    agent=s.agent,
                    action=s.action,
                    status=StepExecutionStatus.BLOCKED,
                    error=f"Step '{s.step_id}' was not executed because prerequisites were unavailable or blocked.",
                )

        # 6. Aggregate final outcome
        overall_status = self._compute_overall_status(step_results)
        overall_answer = self._format_overall_answer(step_results, overall_status)

        return MultiStepExecutionResult(
            plan_id=plan.request_id,
            status=overall_status,
            step_results=step_results,
            overall_answer=overall_answer,
            warnings=[w for res in step_results.values() for w in res.warnings],
            error=self._extract_overall_error(step_results, overall_status),
        )

    @staticmethod
    def _compute_overall_status(
        step_results: dict[str, StepExecutionResult],
    ) -> MultiStepExecutionStatus:
        """
        Aggregate status according to actual step outcomes:
        - CLARIFICATION_REQUIRED: if any step explicitly required clarification.
        - ALL_SUCCEEDED: every required step succeeded.
        - PARTIAL_SUCCESS: at least one step succeeded and at least one step failed or was blocked.
        - FAILED: execution failed without any successful step.
        - BLOCKED: no step could execute because prerequisites were unavailable or blocked.
        """
        results = list(step_results.values())
        if not results:
            return MultiStepExecutionStatus.ALL_SUCCEEDED

        # Check for explicit clarification required
        for r in results:
            if (
                r.output_fields.get("requires_clarification") is True
                or r.action == "clarify"
                or r.error == "clarification_required"
                or r.status == StepExecutionStatus.PENDING
            ):
                return MultiStepExecutionStatus.CLARIFICATION_REQUIRED

        succeeded_count = sum(1 for r in results if r.status == StepExecutionStatus.SUCCEEDED)
        failed_count = sum(1 for r in results if r.status == StepExecutionStatus.FAILED)
        blocked_count = sum(1 for r in results if r.status == StepExecutionStatus.BLOCKED)
        total_count = len(results)

        if succeeded_count == total_count:
            return MultiStepExecutionStatus.ALL_SUCCEEDED
        if succeeded_count > 0 and (failed_count > 0 or blocked_count > 0):
            return MultiStepExecutionStatus.PARTIAL_SUCCESS
        if succeeded_count == 0 and failed_count > 0:
            return MultiStepExecutionStatus.FAILED
        if succeeded_count == 0 and blocked_count > 0 and failed_count == 0:
            return MultiStepExecutionStatus.BLOCKED

        return MultiStepExecutionStatus.FAILED

    @staticmethod
    def _format_overall_answer(
        step_results: dict[str, StepExecutionResult],
        status: MultiStepExecutionStatus,
    ) -> str:
        """
        Build an informative, truthful overall summary message.
        """
        results = list(step_results.values())
        answers = [r.answer.strip() for r in results if r.answer and r.answer.strip()]

        if status == MultiStepExecutionStatus.ALL_SUCCEEDED:
            if answers:
                return "\n".join(answers)
            return "All execution steps succeeded."

        if status == MultiStepExecutionStatus.CLARIFICATION_REQUIRED:
            clarify_answers = [
                r.answer.strip()
                for r in results
                if (
                    r.output_fields.get("requires_clarification") is True
                    or r.action == "clarify"
                    or r.error == "clarification_required"
                    or r.status == StepExecutionStatus.PENDING
                )
                and r.answer
            ]
            if clarify_answers:
                return "\n".join(clarify_answers)
            if answers:
                return "\n".join(answers)
            return "Clarification is required before proceeding."

        summary_parts = []
        for r in results:
            if r.status == StepExecutionStatus.SUCCEEDED:
                summary_parts.append(f"Step '{r.step_id}' ({r.action}): Succeeded.")
            elif r.status == StepExecutionStatus.FAILED:
                err_text = r.error or ""
                if "unhandled exception:" in err_text.lower():
                    err_text = "An internal error occurred during step execution."
                summary_parts.append(f"Step '{r.step_id}' ({r.action}): Failed. {err_text}".strip())
            elif r.status == StepExecutionStatus.BLOCKED:
                summary_parts.append(f"Step '{r.step_id}' ({r.action}): Blocked. {r.error or ''}".strip())
            elif r.status == StepExecutionStatus.SKIPPED:
                summary_parts.append(f"Step '{r.step_id}' ({r.action}): Skipped.")
            elif r.status == StepExecutionStatus.PENDING:
                summary_parts.append(f"Step '{r.step_id}' ({r.action}): Pending.")

        return "\n".join(summary_parts)

    @staticmethod
    def _extract_overall_error(
        step_results: dict[str, StepExecutionResult],
        status: MultiStepExecutionStatus,
    ) -> str | None:
        """
        Extract primary error message if execution was not fully successful.
        """
        if status == MultiStepExecutionStatus.ALL_SUCCEEDED:
            return None
        for r in step_results.values():
            if r.error:
                return r.error
        return None
