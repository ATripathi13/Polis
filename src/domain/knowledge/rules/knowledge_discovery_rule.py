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
    def _subject_from_summary(
        self,
        summary: str,
    ) -> KnowledgeSubject:
        """
        Infer a canonical subject from
        a knowledge statement.
        """

        normalized = summary.lower()

        if "postgresql" in normalized:
            return KnowledgeSubject(
                kind="technology",
                identifier="database",
            )

        return KnowledgeSubject(
            kind="general",
            identifier=normalized,
        )
    
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
            subject=self._subject_from_summary(
                event.summary,
            ),
            summary=event.summary,
            supporting_events=[event],
            confidence=event.confidence,
        )

        return [candidate]