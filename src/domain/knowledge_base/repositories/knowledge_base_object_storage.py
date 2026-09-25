"""
Repository interface for Knowledge Base object storage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class KnowledgeBaseObjectStorage(ABC):
    """
    Stores and retrieves original Knowledge Base files.
    """

    @abstractmethod
    def put(
        self,
        object_key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        object_key: str,
    ) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        object_key: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(
        self,
        object_key: str,
    ) -> bool:
        raise NotImplementedError