"""
Creates knowledge candidates from
knowledge discovery events.
"""

from __future__ import annotations

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)

from ..rules import KnowledgeCandidateRule
from ..value_objects import (
    KnowledgeCandidate,
    KnowledgeSubject,
)


class KnowledgeDiscoveryRule(
    KnowledgeCandidateRule,
):
    """
    Converts knowledge discovery events
    into knowledge candidates.
    """

    def build(
        self,
        event: OrganizationEvent,
    ) -> list[KnowledgeCandidate]:

        if (
            event.event_type
            != OrganizationEventType.KNOWLEDGE_DISCOVERED
        ):
            return []

        candidate = KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="general",
                identifier=event.summary.lower(),
            ),
            summary=event.summary,
            supporting_events=[event],
            confidence=event.confidence,
        )

        return [candidate]