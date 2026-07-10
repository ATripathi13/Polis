"""
Rule-based observation extractor.
"""

from __future__ import annotations

from domain.observation.registry import (
    ObservationRuleRegistry,
)

from domain.observation.services import (
    ObservationExtractor,
)

from domain.observation.value_objects import (
    Observation,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


class RuleBasedObservationExtractor(
    ObservationExtractor,
):
    """
    Executes observation rules in priority order.
    """

    def __init__(
        self,
        registry: ObservationRuleRegistry,
    ) -> None:
        self._registry = registry

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        observations: list[Observation] = []

        for rule in self._registry.rules:

            observations.extend(
                rule.extract(
                    communication,
                )
            )

        return observations