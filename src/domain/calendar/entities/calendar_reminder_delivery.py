"""
Calendar reminder delivery domain entity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from domain.common.identifier import Identifier
from domain.calendar.enums import CalendarDeliveryStatus


@dataclass(slots=True)
class CalendarReminderDelivery:
    """Represents a discrete reminder delivery obligation to a specific recipient."""

    identifier: Identifier
    entry_id: str
    recipient_id: str
    delivery_channel: str  # "dm" or "channel"
    version: int
    due_at: datetime
    status: CalendarDeliveryStatus
    attempt_count: int
    last_attempt_at: datetime | None
    sent_at: datetime | None
    error_message: str | None
    idempotency_key: str
    created_at: datetime
    updated_at: datetime

    @property
    def delivery_id(self) -> str:
        return str(self.identifier.graph_id)

    def mark_processing(self, claim_time: datetime | None = None) -> None:
        """Mark delivery as claimed and currently being processed."""
        self.status = CalendarDeliveryStatus.PROCESSING
        self.last_attempt_at = claim_time or datetime.now(timezone.utc)
        self.attempt_count += 1
        self.updated_at = datetime.now(timezone.utc)

    def mark_sent(self, sent_at: datetime | None = None) -> None:
        """Mark delivery as successfully delivered."""
        now = sent_at or datetime.now(timezone.utc)
        self.status = CalendarDeliveryStatus.SENT
        self.sent_at = now
        self.updated_at = now
        self.error_message = None

    def mark_failed(
        self,
        error_message: str,
        attempt_time: datetime | None = None,
        max_attempts: int = 3,
    ) -> None:
        """Record a delivery attempt failure."""
        now = attempt_time or datetime.now(timezone.utc)
        self.last_attempt_at = now
        self.error_message = error_message[:1000]
        self.status = CalendarDeliveryStatus.FAILED
        self.updated_at = now

    def cancel(self) -> None:
        """Cancel pending delivery obligation."""
        self.status = CalendarDeliveryStatus.CANCELLED
        self.updated_at = datetime.now(timezone.utc)

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        recipient_id: str,
        delivery_channel: str = "dm",
        version: int = 1,
        due_at: datetime,
        status: CalendarDeliveryStatus = CalendarDeliveryStatus.PENDING,
        attempt_count: int = 0,
        last_attempt_at: datetime | None = None,
        sent_at: datetime | None = None,
        error_message: str | None = None,
        idempotency_key: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        business_id: str = "",
    ) -> "CalendarReminderDelivery":
        now = datetime.now(timezone.utc)
        key = idempotency_key or f"cal-rem:{entry_id}:{recipient_id}:v{version}"
        return cls(
            identifier=Identifier(business_id=business_id),
            entry_id=entry_id,
            recipient_id=recipient_id,
            delivery_channel=delivery_channel,
            version=version,
            due_at=due_at,
            status=status,
            attempt_count=attempt_count,
            last_attempt_at=last_attempt_at,
            sent_at=sent_at,
            error_message=error_message,
            idempotency_key=key,
            created_at=created_at or now,
            updated_at=updated_at or now,
        )
