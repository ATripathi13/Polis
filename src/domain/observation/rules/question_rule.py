"""
Extracts question observations.
"""

from __future__ import annotations

from domain.observation.enums import (
    ObservationType,
)

from domain.observation.rules import (
    ObservationRule,
)

from domain.observation.value_objects import (
    Observation,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


class QuestionObservationRule(
    ObservationRule,
):
    """
    Creates QUESTION observations.
    """

    @property
    def priority(self) -> int:
        return 20

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        if not communication.is_question():
            return []

        return [
            Observation(
                observation_type=ObservationType.QUESTION,
                summary=communication.content.body,
                confidence=1.0,
            )
        ]