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

    # def extract(
    #     self,
    #     communication: CommunicationEvent,
    # ) -> list[Observation]:

    #     observations: list[Observation] = []

    #     # for rule in self._registry.rules:

    #     #     observations.extend(
    #     #         rule.extract(
    #     #             communication,
    #     #         )
    #     #     )
    #     print("REGISTERED RULES:", self._registry.rules)

    #     for rule in self._registry.rules:

    #         print("RUNNING:", type(rule).__name__)

    #         result = rule.extract(
    #             communication,
    #         )

    #         print("RESULT:", result)

    #         observations.extend(result)
    #     return observations

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        observations: list[Observation] = []

        print("=" * 80)
        print("COMMUNICATION BODY:", repr(communication.content.body))
        print("REGISTERED RULES:", self._registry.rules)
        
        for rule in self._registry.rules:

            print("RUNNING RULE:", type(rule).__name__)

            result = rule.extract(
                communication,
            )

            print("RULE RESULT:", result)

            observations.extend(result)

        print("FINAL OBSERVATIONS:", observations)
        print("=" * 80)

        return observations