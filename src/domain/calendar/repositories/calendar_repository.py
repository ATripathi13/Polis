"""
Calendar repository abstract interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from domain.calendar.entities.calendar_entry import CalendarEntry
from domain.calendar.entities.calendar_reminder_delivery import (
    CalendarReminderDelivery,
)
from domain.calendar.enums import (
    CalendarAudienceType,
    CalendarEntryStatus,
    CalendarEntryType,
)


class CalendarRepository(ABC):
    """Abstract repository for calendar entries and reminder deliveries."""

    @abstractmethod
    def save_entry(self, entry: CalendarEntry) -> CalendarEntry:
        """Persist or update a calendar entry."""

    @abstractmethod
    def find_entry(self, entry_id: str) -> CalendarEntry | None:
        """Find calendar entry by its ID."""

    @abstractmethod
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
        """Query calendar entries with optional filters."""

    @abstractmethod
    def save_delivery(
        self,
        delivery: CalendarReminderDelivery,
    ) -> CalendarReminderDelivery:
        """Persist or update a reminder delivery obligation."""

    @abstractmethod
    def find_delivery(self, delivery_id: str) -> CalendarReminderDelivery | None:
        """Find delivery by its ID."""

    @abstractmethod
    def find_deliveries_for_entry(
        self,
        entry_id: str,
    ) -> list[CalendarReminderDelivery]:
        """Find all delivery records associated with an entry."""

    @abstractmethod
    def find_due_deliveries(
        self,
        now: datetime,
        limit: int = 50,
    ) -> list[CalendarReminderDelivery]:
        """Find pending reminder deliveries that are due as of now."""

    @abstractmethod
    def claim_due_delivery(
        self,
        delivery_id: str,
        claim_time: datetime,
    ) -> bool:
        """Atomically claim a due delivery for processing."""

    @abstractmethod
    def mark_delivery_sent(
        self,
        delivery_id: str,
        sent_at: datetime,
    ) -> None:
        """Mark a delivery as successfully sent."""

    @abstractmethod
    def mark_delivery_failed(
        self,
        delivery_id: str,
        error_message: str,
        attempt_time: datetime,
        max_attempts: int = 3,
    ) -> None:
        """Record delivery failure and update state."""

    @abstractmethod
    def cancel_pending_deliveries_for_entry(
        self,
        entry_id: str,
    ) -> int:
        """Cancel all pending or processing delivery obligations for an entry."""
