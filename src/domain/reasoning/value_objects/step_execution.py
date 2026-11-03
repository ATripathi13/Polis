"""
Typed domain contracts for Multi-Step Execution in POLIS.

Defines execution statuses, step results, multi-step execution aggregates,
and strictly validated output references between execution steps.
"""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

from .request_plan import ExecutionStep, TargetAgent


class StepExecutionStatus(str, Enum):
    """
    Explicit execution states for an individual execution step.
    """
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class MultiStepExecutionStatus(str, Enum):
    """
    Overall execution outcome for a multi-step cognitive plan.
    """
    ALL_SUCCEEDED = "all_succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    BLOCKED = "blocked"
    CLARIFICATION_REQUIRED = "clarification_required"


class OutputReferenceError(ValueError):
    """Base error for step output reference validation failures."""
    pass


class UndeclaredDependencyReferenceError(OutputReferenceError):
    """Raised when a step references an output from a step not in its dependencies."""
    pass


class SourceStepNotFoundError(OutputReferenceError):
    """Raised when a referenced source step was not found in execution results."""
    pass


class SourceStepNotSucceededError(OutputReferenceError):
    """Raised when a referenced source step did not succeed."""
    pass


class OutputFieldNotFoundError(OutputReferenceError):
    """Raised when a requested field is missing from the source step outputs."""
    pass


class OutputTypeMismatchError(OutputReferenceError):
    """Raised when a resolved output value does not match the expected type."""
    pass


class EmptyOutputValueError(OutputReferenceError):
    """Raised when a resolved output value is empty or None."""
    pass


_APPROVED_PRIMITIVE_TYPES = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": (int, float),
    "bool": bool,
    "boolean": bool,
}


class StepOutputReference(BaseModel):
    """
    Typed reference inside ExecutionStep.parameters pointing to a prerequisite step's output.

    Format in parameters:
        {"$step_ref": "step_1", "field": "entity_id", "expected_type": "str"}
    """
    model_config = ConfigDict(populate_by_name=True)

    step_ref: str = Field(alias="$step_ref")
    field: str = "entity_id"
    expected_type: str = "str"

    @classmethod
    def is_reference(cls, val: Any) -> bool:
        """Check if a value in step parameters represents an output reference."""
        return isinstance(val, dict) and ("$step_ref" in val or "step_ref" in val)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepOutputReference":
        """Construct a validated StepOutputReference from a dictionary."""
        return cls.model_validate(data)

    def validate_and_resolve(
        self,
        current_step: ExecutionStep,
        step_results: dict[str, "StepExecutionResult"],
    ) -> Any:
        """
        Validate reference invariants and resolve actual output value.

        Validates:
        1. Source step exists in declared dependencies.
        2. Source step exists in executed results.
        3. Source step succeeded.
        4. Requested field exists.
        5. Requested value is non-empty.
        6. Actual value matches expected type.
        """
        # 1. Dependency declaration validation
        if self.step_ref not in current_step.dependencies:
            raise UndeclaredDependencyReferenceError(
                f"Step '{current_step.step_id}' references step '{self.step_ref}' "
                f"which is not declared in dependencies: {current_step.dependencies}."
            )

        # 2. Source step presence
        if self.step_ref not in step_results:
            raise SourceStepNotFoundError(
                f"Referenced source step '{self.step_ref}' was not found in executed results."
            )

        source_result = step_results[self.step_ref]

        # 3. Prerequisite success validation
        if source_result.status != StepExecutionStatus.SUCCEEDED:
            raise SourceStepNotSucceededError(
                f"Referenced step '{self.step_ref}' did not succeed "
                f"(status: {source_result.status.value})."
            )

        # 4. Field extraction
        val = source_result.get_output(self.field)
        if val is None:
            raise OutputFieldNotFoundError(
                f"Step '{self.step_ref}' output does not contain field '{self.field}'. "
                f"Available fields: {list(source_result.output_fields.keys())}"
            )

        # 5. Non-empty check
        if isinstance(val, str) and not val.strip():
            raise EmptyOutputValueError(
                f"Step '{self.step_ref}' field '{self.field}' is an empty string."
            )

        # 6. Type validation
        expected = self.expected_type.strip().lower()
        if expected not in _APPROVED_PRIMITIVE_TYPES:
            raise ValueError(
                f"Unsupported expected_type '{self.expected_type}'. "
                f"Approved primitive types: {sorted(list(_APPROVED_PRIMITIVE_TYPES.keys()))}"
            )

        target_type = _APPROVED_PRIMITIVE_TYPES[expected]
        # In Python, bool is a subclass of int. We must strictly prevent bool from masquerading as int or float.
        if expected in ("int", "integer"):
            if not isinstance(val, int) or isinstance(val, bool):
                raise OutputTypeMismatchError(
                    f"Step '{self.step_ref}' field '{self.field}' expected integer, "
                    f"got {type(val).__name__} ({val!r})."
                )
        elif expected in ("float", "number"):
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise OutputTypeMismatchError(
                    f"Step '{self.step_ref}' field '{self.field}' expected number, "
                    f"got {type(val).__name__} ({val!r})."
                )
        elif expected in ("bool", "boolean"):
            if not isinstance(val, bool):
                raise OutputTypeMismatchError(
                    f"Step '{self.step_ref}' field '{self.field}' expected boolean, "
                    f"got {type(val).__name__} ({val!r})."
                )
        elif expected in ("str", "string"):
            if not isinstance(val, str):
                raise OutputTypeMismatchError(
                    f"Step '{self.step_ref}' field '{self.field}' expected string, "
                    f"got {type(val).__name__} ({val!r})."
                )

        return val


class StepExecutionResult(BaseModel):
    """
    Structured outcome of executing an individual ExecutionStep.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    step_id: str
    agent: TargetAgent | str
    action: str
    status: StepExecutionStatus = StepExecutionStatus.PENDING
    entity_id: str | None = None
    entity_type: str | None = None
    output_fields: dict[str, Any] = Field(default_factory=dict)
    answer: str = ""
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    domain_result: Any | None = None

    def get_output(self, field_name: str) -> Any | None:
        """
        Safely retrieve an output field from verified structured domain outputs.
        Checks output_fields first, then direct attributes (entity_id, entity_type).
        """
        if field_name in self.output_fields:
            return self.output_fields[field_name]
        if field_name == "entity_id":
            return self.entity_id
        if field_name == "entity_type":
            return self.entity_type
        return None

    @property
    def is_terminal_failure(self) -> bool:
        """Return True if step ended in a non-recoverable failure or blocked state."""
        return self.status in (StepExecutionStatus.FAILED, StepExecutionStatus.BLOCKED)


class MultiStepExecutionResult(BaseModel):
    """
    Aggregated outcome of executing a multi-step CognitivePlan.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan_id: str
    status: MultiStepExecutionStatus
    step_results: dict[str, StepExecutionResult] = Field(default_factory=dict)
    overall_answer: str = ""
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def is_all_succeeded(self) -> bool:
        return self.status == MultiStepExecutionStatus.ALL_SUCCEEDED

    @property
    def has_failures(self) -> bool:
        return any(res.status == StepExecutionStatus.FAILED for res in self.step_results.values())

    @property
    def has_blocked(self) -> bool:
        return any(res.status == StepExecutionStatus.BLOCKED for res in self.step_results.values())

    def get_step_result(self, step_id: str) -> StepExecutionResult | None:
        return self.step_results.get(step_id)


def resolve_step_parameters(
    step: ExecutionStep,
    step_results: dict[str, StepExecutionResult],
) -> dict[str, Any]:
    """
    Resolve parameter references in a step using successful outputs of prerequisite steps.

    Only evaluates explicit StepOutputReference definitions.
    Rejects undeclared dependencies, missing outputs, or mismatched types.
    Does not evaluate arbitrary Python expressions or string interpolation.
    """
    resolved: dict[str, Any] = {}
    for key, val in step.parameters.items():
        if StepOutputReference.is_reference(val):
            ref = StepOutputReference.from_dict(val)
            resolved[key] = ref.validate_and_resolve(step, step_results)
        else:
            resolved[key] = val
    return resolved
