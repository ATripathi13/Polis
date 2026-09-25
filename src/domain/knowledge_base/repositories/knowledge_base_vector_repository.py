"""
Repository interface for Knowledge Base vector search.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..value_objects import KnowledgeBaseChunk


class KnowledgeBaseVectorRepository(ABC):
    """
    Vector search repository for Knowledge Base chunks.
    """

    @abstractmethod
    def upsert(
        self,
        chunk: KnowledgeBaseChunk,
        embedding: list[float],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_many(
        self,
        chunks: list[KnowledgeBaseChunk],
        embeddings: list[list[float]],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_by_document(
        self,
        document_id: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        embedding: list[float],
        *,
        limit: int = 5,
        document_id: str | None = None,
    ) -> list[tuple[KnowledgeBaseChunk, float]]:
        raise NotImplementedError