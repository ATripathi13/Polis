"""
In-memory implementation of CalendarRepository for testing and validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any

from domain.calendar.entities.calendar_entry import CalendarEntry
from domain.calendar.entities.calendar_reminder_delivery import (
    CalendarReminderDelivery,
)
from domain.calendar.enums import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntryStatus,
    CalendarEntryType,
)
from domain.calendar.repositories.calendar_repository import CalendarRepository


class InMemoryCalendarRepository(CalendarRepository):
    """In-memory thread-safe implementation of CalendarRepository."""

    def __init__(self) -> None:
        self._entries: dict[str, CalendarEntry] = {}
        self._deliveries: dict[str, CalendarReminderDelivery] = {}
        self._lock = threading.Lock()

    def save_entry(self, entry: CalendarEntry) -> CalendarEntry:
        with self._lock:
            self._entries[entry.entry_id] = entry
            return entry

    def find_entry(self, entry_id: str) -> CalendarEntry | None:
        with self._lock:
            return self._entries.get(entry_id)

    def list_entries(
        self,
        *,
        start_range: datetime | None = None,
        end_range: datetime | None = None,
        entry_type: CalendarEntryType | None = None,
        status: CalendarEntryStatus | None = None,
        audience_type: CalendarAudienceType | None = None,
        audience_id: str | None = None,
        limit: int = 100,
    ) -> list[CalendarEntry]:
        with self._lock:
            results = list(self._entries.values())

            if start_range is not None:
                results = [
                    e for e in results
                    if e.start_time >= start_range
                ]
            if end_range is not None:
                results = [
                    e for e in results
                    if e.start_time <= end_range
                ]
            if entry_type is not None:
                results = [
                    e for e in results
                    if e.entry_type == entry_type
                ]
            if status is not None:
                results = [
                    e for e in results
                    if e.status == status
                ]
            if audience_type is not None:
                results = [
                    e for e in results
                    if e.audience_type == audience_type
                ]
            if audience_id is not None:
                results = [
                    e for e in results
                    if e.audience_id == audience_id
                ]

            results.sort(key=lambda e: e.start_time)
            return results[:limit]

    def save_delivery(
        self,
        delivery: CalendarReminderDelivery,
    ) -> CalendarReminderDelivery:
        with self._lock:
            self._deliveries[delivery.delivery_id] = delivery
            return delivery

    def find_delivery(self, delivery_id: str) -> CalendarReminderDelivery | None:
        with self._lock:
            return self._deliveries.get(delivery_id)

    def find_deliveries_for_entry(
        self,
        entry_id: str,
    ) -> list[CalendarReminderDelivery]:
        with self._lock:
            return [
                d for d in self._deliveries.values()
                if d.entry_id == entry_id
            ]

    def find_due_deliveries(
        self,
        now: datetime,
        limit: int = 50,
    ) -> list[CalendarReminderDelivery]:
        with self._lock:
            due = [
                d for d in self._deliveries.values()
                if d.status == CalendarDeliveryStatus.PENDING
                and d.due_at <= now
            ]
            due.sort(key=lambda d: d.due_at)
            return due[:limit]

    def claim_due_delivery(
        self,
        delivery_id: str,
        claim_time: datetime,
    ) -> bool:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
            if delivery is None:
                return False
            if delivery.status != CalendarDeliveryStatus.PENDING:
                return False
            delivery.mark_processing(claim_time)
            return True

    def mark_delivery_sent(
        self,
        delivery_id: str,
        sent_at: datetime,
    ) -> None:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
            if delivery is not None:
                delivery.mark_sent(sent_at)

    def mark_delivery_failed(
        self,
        delivery_id: str,
        error_message: str,
        attempt_time: datetime,
        max_attempts: int = 3,
    ) -> None:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
            if delivery is not None:
                delivery.mark_failed(
                    error_message,
                    attempt_time=attempt_time,
                    max_attempts=max_attempts,
                )

    def cancel_pending_deliveries_for_entry(
        self,
        entry_id: str,
    ) -> int:
        with self._lock:
            cancelled_count = 0
            for delivery in self._deliveries.values():
                if (
                    delivery.entry_id == entry_id
                    and delivery.status in (
                        CalendarDeliveryStatus.PENDING,
                        CalendarDeliveryStatus.PROCESSING,
                    )
                ):
                    delivery.cancel()
                    cancelled_count += 1
            return cancelled_count
