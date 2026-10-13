"""
Converts knowledge observations into organizational events.
"""

from __future__ import annotations

from domain.observation import (
    Observation,
    ObservationType,
)

from domain.organization.enums import (
    OrganizationEventType,
)

from domain.organization.rules import (
    OrganizationEventRule,
)

from domain.organization.value_objects import (
    OrganizationEvent,
)


class KnowledgeOrganizationRule(
    OrganizationEventRule,
):
    """
    Converts knowledge observations into
    organization events with lifecycle support.
    """

    @property
    def priority(self) -> int:
        return 50

    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:

        events: list[OrganizationEvent] = []

        for observation in observations:

            if (
                observation.observation_type
                != ObservationType.KNOWLEDGE
            ):
                continue

            event_type = self._classify_knowledge_event_type(observation)

            events.append(
                OrganizationEvent(
                    event_type=event_type,
                    summary=observation.summary,
                    observations=[
                        observation,
                    ],
                    confidence=observation.confidence,
                    correlation_id=observation.correlation_id,
                    occurred_at=observation.occurred_at,
                )
            )

        return events

    @classmethod
    def _classify_knowledge_event_type(
        cls,
        observation: Observation,
    ) -> OrganizationEventType:
        # 1. Metadata check
        meta = getattr(observation, "metadata", {}) or {}
        if (
            meta.get("is_update")
            or meta.get("lifecycle") == "updated"
            or meta.get("action") == "updated"
        ):
            return OrganizationEventType.KNOWLEDGE_UPDATED

        # 2. Textual semantic cues
        summary_lower = observation.summary.lower().strip()
        update_phrases = (
            "knowledge updated",
            "updated:",
            "update:",
            "no longer use",
            "no longer uses",
            "deprecated:",
            "deprecated in favor of",
            "is deprecated",
            "replaced by",
            "replaced with",
            "migrated from",
            "switched from",
            "correction:",
            "changed from",
        )
        if any(phrase in summary_lower for phrase in update_phrases):
            return OrganizationEventType.KNOWLEDGE_UPDATED

        return OrganizationEventType.KNOWLEDGE_DISCOVERED