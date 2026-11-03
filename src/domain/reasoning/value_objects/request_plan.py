"""
Typed domain contracts for Centralized NLU and Cognitive Planning in POLIS.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class IntentCategory(str, Enum):
    """
    Canonical intent categories supported by POLIS.
    """
    KNOWLEDGE_QUERY = "knowledge_query"
    HISTORICAL_DISCUSSION = "historical_discussion"
    DECISION_QUERY = "decision_query"
    TASK_QUERY = "task_query"
    TASK_ACTION = "task_action"
    RISK_QUERY = "risk_query"
    CALENDAR_QUERY = "calendar_query"
    CALENDAR_ACTION = "calendar_action"
    REMINDER_ACTION = "reminder_action"
    GOVERNANCE_ACTION = "governance_action"
    EMPLOYEE_WORK_QUERY = "employee_work_query"
    ACTIVITY_STATUS_QUERY = "activity_status_query"
    MULTI_AGENT_QUERY = "multi_agent_query"
    GENERAL_CONVERSATION = "general_conversation"
    CLARIFICATION_RESPONSE = "clarification_response"
    CANCEL_ACTION = "cancel_action"
    UNSUPPORTED = "unsupported"


class TargetAgent(str, Enum):
    """
    Specialist agent and capability targets in POLIS.
    """
    KNOWLEDGE_AGENT = "knowledge_agent"
    OPERATIONS_AGENT = "operations_agent"
    CALENDAR_AGENT = "calendar_agent"
    GOVERNANCE_AGENT = "governance_agent"
    ACTIVITY_SERVICE = "activity_service"
    REMINDER_SERVICE = "reminder_service"
    GENERAL_REASONER = "general_reasoner"


class ActionType(str, Enum):
    """
    Nature of the execution step.
    """
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    CANCEL = "cancel"
    CLARIFY = "clarify"


class ExtractedEntities(BaseModel):
    """
    Entities extracted from an employee request.
    """
    employee_names: list[str] = Field(default_factory=list)
    target_user_id: str | None = None
    target_user_name: str | None = None
    team_names: list[str] = Field(default_factory=list)
    project_names: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    times: list[str] = Field(default_factory=list)
    duration_minutes: int | None = None
    event_title: str | None = None
    audience_type: str | None = None
    audience_id: str | None = None
    task_summary: str | None = None
    item_reference: str | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)


class ExecutionStep(BaseModel):
    """
    A single execution step in a cognitive plan.
    """
    step_id: str
    agent: TargetAgent
    action: str
    action_type: ActionType = ActionType.READ
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("step_id cannot be empty.")
        return v.strip()


class CognitivePlan(BaseModel):
    """
    Validated, structured execution plan produced by the cognitive layer.
    """
    request_id: str
    original_message: str
    intent: IntentCategory
    intent_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requested_outcome: str = ""
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    required_agents: list[TargetAgent] = Field(default_factory=list)
    execution_steps: list[ExecutionStep] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_prompt: str | None = None
    action_required: bool = False
    risk_level: Literal["low", "medium", "high", "critical"] = "low"

    @model_validator(mode="after")
    def validate_dependencies_and_cycles(self) -> "CognitivePlan":
        seen_step_ids: set[str] = set()
        for s in self.execution_steps:
            if s.step_id in seen_step_ids:
                raise ValueError(f"Duplicate step_id '{s.step_id}' found in execution steps.")
            seen_step_ids.add(s.step_id)

        step_ids = seen_step_ids

        # Check self-dependency & non-existent reference
        for step in self.execution_steps:
            for dep in step.dependencies:
                if dep == step.step_id:
                    raise ValueError(f"Step '{step.step_id}' cannot depend on itself.")
                if dep not in step_ids:
                    raise ValueError(f"Step '{step.step_id}' references unknown dependency '{dep}'.")

        # Cycle detection via DFS
        adj: dict[str, list[str]] = {s.step_id: s.dependencies for s in self.execution_steps}
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
                    raise ValueError(f"Dependency cycle detected in execution steps including '{sid}'.")

        # Action safety invariants: missing information or clarification requirement prohibits action authorization
        if self.missing_information and self.action_required:
            raise ValueError("action_required cannot be True when missing_information is non-empty.")
        if self.requires_clarification and self.action_required and self.intent != IntentCategory.CANCEL_ACTION:
            raise ValueError("action_required cannot be True when requires_clarification is True.")

        return self


def parse_and_validate_iso_timestamp(ts: str, field_name: str) -> datetime:
    """Parse an ISO timestamp, strictly enforcing valid formatting and returning timezone-aware UTC datetime."""
    if not ts or not isinstance(ts, str) or not ts.strip():
        raise ValueError(f"{field_name} must be a non-empty ISO timestamp string.")
    try:
        # Standard Python datetime.fromisoformat
        dt = datetime.fromisoformat(ts.strip())
        if dt.tzinfo is None:
            # Treat legacy naive timestamp as UTC
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception as e:
        raise ValueError(f"{field_name} '{ts}' is not a valid ISO 8601 timestamp: {e}")


class PendingOperation(BaseModel):
    """
    Active multi-turn pending operation context.

    Preserves state across conversational follow-ups (e.g., date/time clarification
    in a scheduling flow) scoped strictly to user, channel, and thread.
    """
    operation_id: str
    intent: IntentCategory = IntentCategory.GENERAL_CONVERSATION
    target_agent: TargetAgent = TargetAgent.GENERAL_REASONER
    action: str = ""
    collected_entities: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    clarification_question: str = ""
    user_id: str
    channel_id: str
    thread_ts: str = ""
    created_at_iso: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at_iso: str
    state_version: int = 1
    plan_id: str | None = None
    original_plan: dict[str, Any] | None = None
    step_states: dict[str, str] = Field(default_factory=dict)
    completed_step_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    pending_step_id: str | None = None
    uncertain_step_ids: list[str] = Field(default_factory=list)

    @field_validator("state_version")
    @classmethod
    def validate_state_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"Unsupported state_version {v}. Only version 1 is supported.")
        return v

    @field_validator("user_id", "channel_id", "operation_id")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        if not v or not str(v).strip():
            raise ValueError(f"{info.field_name} cannot be empty.")
        return str(v).strip()

    @field_validator("thread_ts")
    @classmethod
    def validate_thread_ts(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("created_at_iso")
    @classmethod
    def validate_created_at(cls, v: str) -> str:
        if not v or not str(v).strip():
            return datetime.now(timezone.utc).isoformat()
        parse_and_validate_iso_timestamp(v, "created_at_iso")
        return v.strip()

    @field_validator("expires_at_iso")
    @classmethod
    def validate_expires_at(cls, v: str) -> str:
        parse_and_validate_iso_timestamp(v, "expires_at_iso")
        return v.strip()

    @model_validator(mode="after")
    def validate_time_order(self) -> "PendingOperation":
        c_dt = parse_and_validate_iso_timestamp(self.created_at_iso, "created_at_iso")
        e_dt = parse_and_validate_iso_timestamp(self.expires_at_iso, "expires_at_iso")
        if e_dt <= c_dt:
            raise ValueError("expires_at_iso must be strictly after created_at_iso.")
        return self

    @property
    def is_multi_step(self) -> bool:
        """Return True if this pending operation represents a multi-step plan."""
        return bool(self.plan_id and (self.original_plan or self.completed_step_results))

    def get_original_plan(self) -> "CognitivePlan" | None:
        """Reconstruct original CognitivePlan model."""
        if not self.original_plan:
            return None
        try:
            return CognitivePlan.model_validate(self.original_plan)
        except Exception:
            return None

    def get_completed_results(self) -> dict[str, Any]:
        """
        Reconstruct StepExecutionResult objects from serialized completed_step_results.
        """
        from .step_execution import StepExecutionResult
        reconstructed = {}
        for sid, data in self.completed_step_results.items():
            if isinstance(data, dict):
                clean_data = dict(data)
                clean_data["domain_result"] = None
                reconstructed[sid] = StepExecutionResult.model_validate(clean_data)
        return reconstructed
