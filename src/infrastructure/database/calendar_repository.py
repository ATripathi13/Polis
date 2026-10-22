"""
PostgreSQL implementation of the CalendarRepository.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import update

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
from domain.common.identifier import Identifier
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import (
    CalendarEntryModel,
    CalendarReminderDeliveryModel,
)

logger = logging.getLogger(__name__)


class PostgreSQLCalendarRepository(CalendarRepository):
    """PostgreSQL-backed repository for calendar entries and reminder deliveries."""

    @staticmethod
    def _to_entry(model: CalendarEntryModel) -> CalendarEntry:
        return CalendarEntry(
            identifier=Identifier(business_id=model.id),
            title=model.title,
            description=model.description,
            entry_type=CalendarEntryType(model.entry_type),
            creator_id=model.creator_id,
            start_time=model.start_time,
            end_time=model.end_time,
            timezone=model.timezone,
            audience_type=CalendarAudienceType(model.audience_type),
            audience_id=model.audience_id,
            status=CalendarEntryStatus(model.status),
            version=model.version,
            metadata=dict(model.metadata_ or {}),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_delivery(
        model: CalendarReminderDeliveryModel,
    ) -> CalendarReminderDelivery:
        return CalendarReminderDelivery(
            identifier=Identifier(business_id=model.id),
            entry_id=model.entry_id,
            recipient_id=model.recipient_id,
            delivery_channel=model.delivery_channel,
            version=model.version,
            due_at=model.due_at,
            status=CalendarDeliveryStatus(model.status),
            attempt_count=model.attempt_count,
            last_attempt_at=model.last_attempt_at,
            sent_at=model.sent_at,
            error_message=model.error_message,
            idempotency_key=model.idempotency_key,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def save_entry(self, entry: CalendarEntry) -> CalendarEntry:
        with SessionLocal() as session:
            record = session.get(CalendarEntryModel, entry.entry_id)
            if record is None:
                record = CalendarEntryModel(id=entry.entry_id)
                session.add(record)

            record.title = entry.title
            record.description = entry.description
            record.entry_type = entry.entry_type.value
            record.creator_id = entry.creator_id
            record.start_time = entry.start_time
            record.end_time = entry.end_time
            record.timezone = entry.timezone
            record.audience_type = entry.audience_type.value
            record.audience_id = entry.audience_id
            record.status = entry.status.value
            record.version = entry.version
            record.metadata_ = dict(entry.metadata)
            record.created_at = entry.created_at
            record.updated_at = entry.updated_at

            session.commit()
            session.refresh(record)
            return self._to_entry(record)

    def find_entry(self, entry_id: str) -> CalendarEntry | None:
        if not entry_id:
            return None
        with SessionLocal() as session:
            record = session.get(CalendarEntryModel, entry_id)
            return self._to_entry(record) if record else None

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
        with SessionLocal() as session:
            query = session.query(CalendarEntryModel)

            if start_range is not None:
                query = query.filter(CalendarEntryModel.start_time >= start_range)
            if end_range is not None:
                query = query.filter(CalendarEntryModel.start_time <= end_range)
            if entry_type is not None:
                query = query.filter(CalendarEntryModel.entry_type == entry_type.value)
            if status is not None:
                query = query.filter(CalendarEntryModel.status == status.value)
            if audience_type is not None:
                query = query.filter(CalendarEntryModel.audience_type == audience_type.value)
            if audience_id is not None:
                query = query.filter(CalendarEntryModel.audience_id == audience_id)

            records = (
                query.order_by(CalendarEntryModel.start_time.asc())
                .limit(limit)
                .all()
            )
            return [self._to_entry(r) for r in records]

    def save_delivery(
        self,
        delivery: CalendarReminderDelivery,
    ) -> CalendarReminderDelivery:
        with SessionLocal() as session:
            record = session.get(
                CalendarReminderDeliveryModel,
                delivery.delivery_id,
            )
            if record is None:
                record = CalendarReminderDeliveryModel(id=delivery.delivery_id)
                session.add(record)

            record.entry_id = delivery.entry_id
            record.recipient_id = delivery.recipient_id
            record.delivery_channel = delivery.delivery_channel
            record.version = delivery.version
            record.due_at = delivery.due_at
            record.status = delivery.status.value
            record.attempt_count = delivery.attempt_count
            record.last_attempt_at = delivery.last_attempt_at
            record.sent_at = delivery.sent_at
            record.error_message = delivery.error_message
            record.idempotency_key = delivery.idempotency_key
            record.created_at = delivery.created_at
            record.updated_at = delivery.updated_at

            session.commit()
            session.refresh(record)
            return self._to_delivery(record)

    def find_delivery(self, delivery_id: str) -> CalendarReminderDelivery | None:
        if not delivery_id:
            return None
        with SessionLocal() as session:
            record = session.get(CalendarReminderDeliveryModel, delivery_id)
            return self._to_delivery(record) if record else None

    def find_deliveries_for_entry(
        self,
        entry_id: str,
    ) -> list[CalendarReminderDelivery]:
        if not entry_id:
            return []
        with SessionLocal() as session:
            records = (
                session.query(CalendarReminderDeliveryModel)
                .filter(CalendarReminderDeliveryModel.entry_id == entry_id)
                .order_by(CalendarReminderDeliveryModel.created_at.asc())
                .all()
            )
            return [self._to_delivery(r) for r in records]

    def find_due_deliveries(
        self,
        now: datetime,
        limit: int = 50,
    ) -> list[CalendarReminderDelivery]:
        with SessionLocal() as session:
            records = (
                session.query(CalendarReminderDeliveryModel)
                .filter(
                    CalendarReminderDeliveryModel.status
                    == CalendarDeliveryStatus.PENDING.value,
                    CalendarReminderDeliveryModel.due_at <= now,
                )
                .order_by(CalendarReminderDeliveryModel.due_at.asc())
                .limit(limit)
                .all()
            )
            return [self._to_delivery(r) for r in records]

    def claim_due_delivery(
        self,
        delivery_id: str,
        claim_time: datetime,
    ) -> bool:
        """
        Atomically claim a due delivery for processing using optimistic locking.
        """
        with SessionLocal() as session:
            stmt = (
                update(CalendarReminderDeliveryModel)
                .where(
                    CalendarReminderDeliveryModel.id == delivery_id,
                    CalendarReminderDeliveryModel.status
                    == CalendarDeliveryStatus.PENDING.value,
                )
                .values(
                    status=CalendarDeliveryStatus.PROCESSING.value,
                    last_attempt_at=claim_time,
                    attempt_count=CalendarReminderDeliveryModel.attempt_count + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0

    def mark_delivery_sent(
        self,
        delivery_id: str,
        sent_at: datetime,
    ) -> None:
        with SessionLocal() as session:
            stmt = (
                update(CalendarReminderDeliveryModel)
                .where(CalendarReminderDeliveryModel.id == delivery_id)
                .values(
                    status=CalendarDeliveryStatus.SENT.value,
                    sent_at=sent_at,
                    error_message=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.execute(stmt)
            session.commit()

    def mark_delivery_failed(
        self,
        delivery_id: str,
        error_message: str,
        attempt_time: datetime,
        max_attempts: int = 3,
    ) -> None:
        with SessionLocal() as session:
            stmt = (
                update(CalendarReminderDeliveryModel)
                .where(CalendarReminderDeliveryModel.id == delivery_id)
                .values(
                    status=CalendarDeliveryStatus.FAILED.value,
                    error_message=error_message[:1000],
                    last_attempt_at=attempt_time,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.execute(stmt)
            session.commit()

    def cancel_pending_deliveries_for_entry(
        self,
        entry_id: str,
    ) -> int:
        with SessionLocal() as session:
            stmt = (
                update(CalendarReminderDeliveryModel)
                .where(
                    CalendarReminderDeliveryModel.entry_id == entry_id,
                    CalendarReminderDeliveryModel.status.in_(
                        [
                            CalendarDeliveryStatus.PENDING.value,
                            CalendarDeliveryStatus.PROCESSING.value,
                        ]
                    ),
                )
                .values(
                    status=CalendarDeliveryStatus.CANCELLED.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount
