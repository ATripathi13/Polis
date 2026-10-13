"""
Converts operational observations into organizational events.
"""

from __future__ import annotations

from domain.observation import (
    Observation,
    ObservationType,
)

from domain.organization.enums import (
    OrganizationEventType,
)

from domain.organization.rules import (
    OrganizationEventRule,
)

from domain.organization.value_objects import (
    OrganizationEvent,
)


class OperationalOrganizationRule(
    OrganizationEventRule,
):
    """
    Converts task, decision, and risk observations
    into operational organization events with lifecycle support.
    """

    @property
    def priority(self) -> int:
        return 40

    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:

        events: list[OrganizationEvent] = []

        for observation in observations:
            event_type = self._classify_event_type(observation)

            if event_type is None:
                continue

            events.append(
                OrganizationEvent(
                    event_type=event_type,
                    summary=observation.summary,
                    observations=[observation],
                    confidence=observation.confidence,
                    correlation_id=observation.correlation_id,
                    occurred_at=observation.occurred_at,
                )
            )

        return events

    @classmethod
    def _classify_event_type(
        cls,
        observation: Observation,
    ) -> OrganizationEventType | None:
        if observation.observation_type == ObservationType.DECISION:
            return OrganizationEventType.DECISION_MADE

        if observation.observation_type == ObservationType.RISK:
            return OrganizationEventType.RISK_IDENTIFIED

        if observation.observation_type == ObservationType.TASK:
            return cls._classify_task_event_type(observation)

        return None

    @classmethod
    def _classify_task_event_type(
        cls,
        observation: Observation,
    ) -> OrganizationEventType:
        # 1. Structured metadata cues
        meta = getattr(observation, "metadata", {}) or {}
        explicit_status = str(meta.get("status", "")).lower().strip()
        explicit_action = str(meta.get("action", "")).lower().strip()
        explicit_lifecycle = str(meta.get("lifecycle", "")).lower().strip()

        completion_tokens = {
            "completed",
            "complete",
            "done",
            "finished",
            "closed",
            "resolved",
        }
        update_tokens = {
            "updated",
            "in_progress",
            "in progress",
            "rescheduled",
            "reassigned",
            "paused",
            "blocked",
        }

        if (
            explicit_status in completion_tokens
            or explicit_action in completion_tokens
            or explicit_lifecycle in completion_tokens
        ):
            return OrganizationEventType.TASK_COMPLETED

        if (
            explicit_status in update_tokens
            or explicit_action in update_tokens
            or explicit_lifecycle in update_tokens
        ):
            return OrganizationEventType.TASK_UPDATED

        # 2. Textual summary semantics
        summary_lower = observation.summary.lower().strip()

        completion_phrases = (
            "task completed",
            "task is completed",
            "task has been completed",
            "task complete",
            "marked as completed",
            "marked completed",
            "completed the task",
            "completed task",
            "task finished",
            "finished the task",
            "finished task",
            "task is done",
            "marked as done",
            "task resolved",
            "resolved the task",
            "task closed",
            "closed the task",
            "is completed",
            "has been completed",
            "was completed",
            "is finished",
            "has been finished",
        )
        if any(phrase in summary_lower for phrase in completion_phrases):
            return OrganizationEventType.TASK_COMPLETED

        update_phrases = (
            "task updated",
            "updated task",
            "task is now in progress",
            "task in progress",
            "is now in progress",
            "task rescheduled",
            "rescheduled task",
            "deadline changed",
            "deadline updated",
            "status update:",
            "task status updated",
            "task reassigned",
            "reassigned task",
            "moved deadline",
            "postponed task",
        )
        if any(phrase in summary_lower for phrase in update_phrases):
            return OrganizationEventType.TASK_UPDATED

        # Default for identified work
        return OrganizationEventType.TASK_CREATED
