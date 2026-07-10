"""
Registry for observation rules.
"""

from __future__ import annotations

from domain.observation.rules import (
    ObservationRule,
)


class ObservationRuleRegistry:
    """
    Stores observation rules in priority order.
    """

    def __init__(self) -> None:
        self._rules: list[ObservationRule] = []

    def register(
        self,
        rule: ObservationRule,
    ) -> None:

        self._rules.append(rule)

        self._rules.sort(
            key=lambda r: r.priority,
        )

    @property
    def rules(
        self,
    ) -> list[ObservationRule]:

        return self._rules