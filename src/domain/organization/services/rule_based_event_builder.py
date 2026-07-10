"""
Rule-based organizational event builder.
"""

from __future__ import annotations

from domain.observation import (
    Observation,
)

from domain.organization.registry import (
    OrganizationEventRuleRegistry,
)

from domain.organization.services import (
    OrganizationEventBuilder,
)

from domain.organization.value_objects import (
    OrganizationEvent,
)


class RuleBasedOrganizationEventBuilder(
    OrganizationEventBuilder,
):
    """
    Executes organization event rules.
    """

    def __init__(
        self,
        registry: OrganizationEventRuleRegistry,
    ) -> None:
        self._registry = registry

    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:

        events: list[OrganizationEvent] = []

        for rule in self._registry.rules:

            events.extend(
                rule.build(
                    observations,
                )
            )

        return events