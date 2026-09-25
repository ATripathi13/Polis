"""
Repository interface for Knowledge Base documents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..value_objects import KnowledgeBaseDocument


class KnowledgeBaseDocumentRepository(ABC):
    """
    Repository for persisted Knowledge Base documents.
    """

    @abstractmethod
    def save(
        self,
        document: KnowledgeBaseDocument,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find(
        self,
        document_id: str,
    ) -> KnowledgeBaseDocument | None:
        raise NotImplementedError

    @abstractmethod
    def find_by_checksum(
        self,
        checksum: str,
    ) -> KnowledgeBaseDocument | None:
        raise NotImplementedError

    @abstractmethod
    def all(
        self,
    ) -> list[KnowledgeBaseDocument]:
        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        document_id: str,
    ) -> None:
        raise NotImplementedError