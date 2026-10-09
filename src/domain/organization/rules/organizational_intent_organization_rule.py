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


class OrganizationalIntentOrganizationRule(
    OrganizationEventRule,
):
    """
    Converts approval, contradiction, policy-violation alerts,
    and summary-request observations into canonical events.
    """

    @property
    def priority(self) -> int:
        return 30

    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:

        event_mapping = {
            ObservationType.APPROVAL: (
                OrganizationEventType.APPROVAL_GRANTED
            ),
            ObservationType.CONTRADICTION: (
                OrganizationEventType.CONTRADICTION_DETECTED
            ),
            ObservationType.ALERT: (
                OrganizationEventType.POLICY_VIOLATION
            ),
            ObservationType.SUMMARY_REQUEST: (
                OrganizationEventType.SUMMARY_REQUESTED
            ),
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
