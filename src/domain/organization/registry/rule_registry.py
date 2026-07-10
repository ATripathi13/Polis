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

        self._rules.append(rule)

        self._rules.sort(
            key=lambda r: r.priority,
        )

    @property
    def rules(
        self,
    ) -> list[OrganizationEventRule]:

        return self._rules