"""
Converts knowledge observations into organizational events.
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


class KnowledgeOrganizationRule(
    OrganizationEventRule,
):
    """
    Converts knowledge observations into
    organization events.
    """

    @property
    def priority(self) -> int:
        return 50

    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:

        events: list[OrganizationEvent] = []

        for observation in observations:

            if (
                observation.observation_type
                != ObservationType.KNOWLEDGE
            ):
                continue

            events.append(
                OrganizationEvent(
                    event_type=(
                        OrganizationEventType
                        .KNOWLEDGE_DISCOVERED
                    ),
                    summary=observation.summary,
                    observations=[
                        observation,
                    ],
                    confidence=observation.confidence,
                )
            )

        return events