"""
Repository contract for the Polis Domain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from domain.common.entity import Entity
from domain.common.identifier import Identifier

TEntity = TypeVar("TEntity", bound=Entity)


class Repository(ABC, Generic[TEntity]):
    """
    Base repository contract.

    Infrastructure implementations must implement this interface.
    """

    @abstractmethod
    def get(self, identifier: Identifier) -> TEntity | None:
        """Return an entity by identifier."""

    @abstractmethod
    def save(self, entity: TEntity) -> None:
        """Persist an entity."""

    @abstractmethod
    def delete(self, identifier: Identifier) -> None:
        """Delete (or soft delete) an entity."""

    @abstractmethod
    def exists(self, identifier: Identifier) -> bool:
        """Check whether an entity exists."""