"""
Repository interface for validated knowledge.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..value_objects import (
    KnowledgeCandidate,
)


class KnowledgeRepository(ABC):
    """
    Repository for storing validated
    organizational knowledge.
    """

    @abstractmethod
    def save(
        self,
        candidate: KnowledgeCandidate,
    ) -> None:
        """
        Store validated knowledge.
        """
        raise NotImplementedError

    @abstractmethod
    def find(
        self,
        identifier: str,
    ) -> KnowledgeCandidate | None:
        """
        Find knowledge by identifier.
        """
        raise NotImplementedError

    @abstractmethod
    def all(
        self,
    ) -> list[KnowledgeCandidate]:
        """
        Return all stored knowledge.
        """
        raise NotImplementedError