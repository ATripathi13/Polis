"""
Converts question observations into organizational events.
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


class QuestionOrganizationRule(
    OrganizationEventRule,
):
    """
    Converts question observations into
    organization events.
    """

    @property
    def priority(self) -> int:
        return 20

    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:

        events: list[OrganizationEvent] = []

        for observation in observations:

            if (
                observation.observation_type
                != ObservationType.QUESTION
            ):
                continue

            events.append(
                OrganizationEvent(
                    event_type=(
                        OrganizationEventType
                        .QUESTION_ASKED
                    ),
                    summary=observation.summary,
                    observations=[
                        observation,
                    ],
                    confidence=observation.confidence,
                )
            )

        return events
