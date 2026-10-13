"""
Registry for organization event rules.
"""

from __future__ import annotations

from domain.organization.rules import (
    OrganizationEventRule,
)


class OrganizationEventRuleRegistry:
    """
    Stores organization event rules
    in execution order.
    """

    def __init__(self) -> None:
        self._rules: list[OrganizationEventRule] = []

    def register(
        self,
        rule: OrganizationEventRule,
    ) -> None:
        if rule not in self._rules:
            self._rules.append(rule)

        self._rules.sort(
            key=lambda r: (r.priority, r.__class__.__name__),
        )

    @property
    def rules(
        self,
    ) -> list[OrganizationEventRule]:
        return list(self._rules)