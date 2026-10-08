from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..entities import OperationalItem
from ..enums import OperationalItemStatus, OperationalItemType


class OperationalItemRepository(ABC):
    """
    Repository contract for persistent operational items.
    """

    @abstractmethod
    def save(
        self,
        item: OperationalItem,
    ) -> OperationalItem:
        raise NotImplementedError

    @abstractmethod
    def find_by_id(
        self,
        item_id: str,
    ) -> OperationalItem | None:
        raise NotImplementedError

    @abstractmethod
    def find_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
        item_type: OperationalItemType,
    ) -> OperationalItem | None:
        raise NotImplementedError

    @abstractmethod
    def find_open(
        self,
        *,
        item_type: OperationalItemType | None = None,
        owner_id: str | None = None,
    ) -> list[OperationalItem]:
        raise NotImplementedError

    @abstractmethod
    def find_overdue(
        self,
        now: datetime,
    ) -> list[OperationalItem]:
        raise NotImplementedError

    @abstractmethod
    def update_status(
        self,
        item_id: str,
        status: OperationalItemStatus,
    ) -> OperationalItem | None:
        raise NotImplementedError
