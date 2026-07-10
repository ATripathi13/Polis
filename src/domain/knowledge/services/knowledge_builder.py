"""
Base knowledge builder.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.organization.value_objects import (
    OrganizationEvent,
)

from ..value_objects import (
    KnowledgeCandidate,
)


class KnowledgeBuilder(ABC):
    """
    Builds knowledge candidates
    from organization events.
    """

    @abstractmethod
    def build(
        self,
        event: OrganizationEvent,
    ) -> list[KnowledgeCandidate]:
        raise NotImplementedError