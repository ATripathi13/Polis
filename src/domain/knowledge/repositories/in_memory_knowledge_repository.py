"""
In-memory knowledge repository.
"""

from __future__ import annotations

from .knowledge_repository import (
    KnowledgeRepository,
)

from ..value_objects import (
    KnowledgeCandidate,
)


class InMemoryKnowledgeRepository(
    KnowledgeRepository,
):
    """
    Stores validated knowledge in memory.
    """

    def __init__(self) -> None:

        self._knowledge: dict[
            str,
            KnowledgeCandidate,
        ] = {}

    def save(
        self,
        candidate: KnowledgeCandidate,
    ) -> None:

        self._knowledge[
            candidate.subject.identifier
        ] = candidate

    def find(
        self,
        identifier: str,
    ) -> KnowledgeCandidate | None:

        return self._knowledge.get(
            identifier,
        )

    def all(
        self,
    ) -> list[KnowledgeCandidate]:

        return list(
            self._knowledge.values()
        )