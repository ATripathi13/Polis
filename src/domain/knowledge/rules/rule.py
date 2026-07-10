"""
Base knowledge candidate rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.organization import (
    OrganizationEvent,
)

from ..value_objects import (
    KnowledgeCandidate,
)


class KnowledgeCandidateRule(ABC):
    """
    Creates candidate knowledge from
    organizational events.
    """

    @property
    def priority(self) -> int:
        return 100

    @abstractmethod
    def build(
        self,
        event: OrganizationEvent,
    ) -> list[KnowledgeCandidate]:
        """
        Build knowledge candidates.
        """
        raise NotImplementedError