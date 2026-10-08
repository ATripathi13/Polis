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
    into operational organization events.
    """

    @property
    def priority(self) -> int:
        return 40

    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:

        event_mapping = {
            ObservationType.TASK: OrganizationEventType.TASK_CREATED,
            ObservationType.DECISION: OrganizationEventType.DECISION_MADE,
            ObservationType.RISK: OrganizationEventType.RISK_IDENTIFIED,
        }

        events: list[OrganizationEvent] = []

        for observation in observations:
            event_type = event_mapping.get(
                observation.observation_type
            )

            if event_type is None:
                continue

            events.append(
                OrganizationEvent(
                    event_type=event_type,
                    summary=observation.summary,
                    observations=[observation],
                    confidence=observation.confidence,
                )
            )

        return events
