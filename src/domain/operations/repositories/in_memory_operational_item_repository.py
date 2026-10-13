"""
In-memory implementation of OperationalItemRepository.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from domain.operations.entities import OperationalItem
from domain.operations.enums import OperationalItemStatus, OperationalItemType
from .operational_item_repository import OperationalItemRepository


class InMemoryOperationalItemRepository(OperationalItemRepository):
    """
    Stores operational items in memory for high-speed, isolated unit testing.
    """

    def __init__(self) -> None:
        self._items: dict[str, OperationalItem] = {}

    def save(
        self,
        item: OperationalItem,
    ) -> OperationalItem:
        key = str(item.identifier.graph_id)

        # 1. Update if item with same ID exists
        if key in self._items:
            self._items[key] = item
            return item

        # 2. Idempotency check: if item with same source_type, source_event_id, and item_type exists
        if item.source_event_id:
            for existing in self._items.values():
                if (
                    existing.source_type == item.source_type
                    and existing.source_event_id == item.source_event_id
                    and existing.item_type == item.item_type
                ):
                    return existing

        self._items[key] = item
        return item

    def find_by_id(
        self,
        item_id: str,
    ) -> OperationalItem | None:
        return self._items.get(item_id)

    def find_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
        item_type: OperationalItemType,
    ) -> OperationalItem | None:
        for item in self._items.values():
            if (
                item.source_type == source_type
                and item.source_event_id == source_event_id
                and item.item_type == item_type
            ):
                return item
        return None

    def find_by_correlation(
        self,
        correlation_id: str,
        *,
        item_type: OperationalItemType | None = None,
    ) -> list[OperationalItem]:
        matches = []
        for item in self._items.values():
            item_corr = item.metadata.get("correlation_id")
            if item_corr and str(item_corr) == str(correlation_id):
                if item_type is None or item.item_type == item_type:
                    matches.append(item)
        return matches

    def find_open(
        self,
        *,
        item_type: OperationalItemType | None = None,
        owner_id: str | None = None,
    ) -> list[OperationalItem]:
        results = []
        open_statuses = {
            OperationalItemStatus.OPEN,
            OperationalItemStatus.IN_PROGRESS,
        }
        for item in self._items.values():
            if item.status in open_statuses:
                if item_type is not None and item.item_type != item_type:
                    continue
                if owner_id is not None and item.owner_id != owner_id:
                    continue
                results.append(item)
        return sorted(results, key=lambda i: i.created_at, reverse=True)

    def find_overdue(
        self,
        now: datetime,
    ) -> list[OperationalItem]:
        results = []
        open_statuses = {
            OperationalItemStatus.OPEN,
            OperationalItemStatus.IN_PROGRESS,
        }
        for item in self._items.values():
            if (
                item.due_at is not None
                and item.due_at < now
                and item.status in open_statuses
            ):
                results.append(item)
        return sorted(results, key=lambda i: i.due_at or now)

    def update_status(
        self,
        item_id: str,
        status: OperationalItemStatus,
    ) -> OperationalItem | None:
        item = self._items.get(item_id)
        if item is None:
            return None
        item.status = status
        item.touch()
        return item

    def all(self) -> list[OperationalItem]:
        return list(self._items.values())

    def clear(self) -> None:
        self._items.clear()
