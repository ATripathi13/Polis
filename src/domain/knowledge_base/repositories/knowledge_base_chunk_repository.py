"""
Repository interface for Knowledge Base chunks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..value_objects import KnowledgeBaseChunk


class KnowledgeBaseChunkRepository(ABC):
    """
    Repository for persisted Knowledge Base chunks.
    """

    @abstractmethod
    def save(
        self,
        chunk: KnowledgeBaseChunk,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_many(
        self,
        chunks: list[KnowledgeBaseChunk],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_by_document(
        self,
        document_id: str,
    ) -> list[KnowledgeBaseChunk]:
        raise NotImplementedError

    @abstractmethod
    def delete_by_document(
        self,
        document_id: str,
    ) -> None:
        raise NotImplementedError