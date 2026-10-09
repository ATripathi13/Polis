"""
Rule-based observation extractor.
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


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

            try:
                result = rule.extract(
                    communication,
                )
            except Exception:
                logger.exception(
                    "Observation rule failed: %s",
                    type(rule).__name__,
                )
                continue

            observations.extend(result)

        return observations
