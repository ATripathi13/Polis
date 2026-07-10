"""
Extracts knowledge observations from communications.
"""

from __future__ import annotations

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.observation.enums import (
    ObservationType,
)

from domain.observation.rules import (
    ObservationRule,
)

from domain.observation.value_objects import (
    Observation,
)


class KnowledgeObservationRule(
    ObservationRule,
):
    """
    Detects organizational knowledge statements.
    """

    _PATTERNS = (
        "we use",
        "we have",
        "we deploy",
        "we run",
        "we store",
        "our ",
        "the company",
    )

    @property
    def priority(self) -> int:
        return 50

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        text = communication.content.body.strip()

        if not text:
            return []

        normalized = text.lower()

        if not any(
            normalized.startswith(pattern)
            for pattern in self._PATTERNS
        ):
            return []

        return [
            Observation(
                observation_type=ObservationType.KNOWLEDGE,
                summary=text,
                confidence=1.0,
                evidence=[
                    communication.source_event_id,
                ],
            )
        ]