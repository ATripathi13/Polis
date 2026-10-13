"""
Rule-based organizational event builder.
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


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

        raw_events: list[OrganizationEvent] = []

        for rule in self._registry.rules:

            try:
                raw_events.extend(
                    rule.build(
                        observations,
                    )
                )
            except Exception:
                logger.exception(
                    "Organization event rule failed: %s",
                    type(rule).__name__,
                )
                continue

        deduped: list[OrganizationEvent] = []
        seen: set[tuple[object, str, tuple[str, ...]]] = set()

        for event in raw_events:
            evidence_tuple = tuple(
                sorted(
                    {
                        ev
                        for obs in event.observations
                        for ev in obs.evidence
                        if ev and ev.strip()
                    }
                )
            )
            key = (
                event.event_type,
                event.summary.strip().lower(),
                evidence_tuple,
            )
            if key not in seen:
                seen.add(key)
                deduped.append(event)

        return deduped
