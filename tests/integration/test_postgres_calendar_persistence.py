"""
Integration tests for PostgreSQLCalendarRepository with isolated test database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4
import pytest

from domain.calendar import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntry,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderDelivery,
)
from infrastructure.database.calendar_repository import PostgreSQLCalendarRepository
from infrastructure.database.models import (
    CalendarEntryModel,
    CalendarReminderDeliveryModel,
)
from tests.staging_safety_gate import staging_safety_gate


@pytest.fixture
def postgres_calendar_repo(staging_safety_gate):
    """Use only the explicitly configured and validated isolated polis_test database."""
    _, session_factory = staging_safety_gate
    yield PostgreSQLCalendarRepository(), session_factory


def test_postgres_calendar_entry_roundtrip(postgres_calendar_repo):
    repo, session_factory = postgres_calendar_repo
    now = datetime.now(timezone.utc)
    unique_suffix = uuid4().hex
    entry = CalendarEntry.create(
        title=f"Postgres Integration Test Event {unique_suffix}",
        description="Verifying PostgreSQL persistence",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id=f"U_PG_TEST_{unique_suffix}",
        start_time=now + timedelta(days=1),
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_id=f"U_PG_TARGET_{unique_suffix}",
    )

    saved = None
    try:
        saved = repo.save_entry(entry)
        retrieved = repo.find_entry(saved.entry_id)

        assert retrieved is not None
        assert retrieved.entry_id == saved.entry_id
        assert retrieved.title == f"Postgres Integration Test Event {unique_suffix}"
        assert retrieved.entry_type == CalendarEntryType.ACTIVITY
        assert retrieved.creator_id == f"U_PG_TEST_{unique_suffix}"
    finally:
        if saved is not None:
            with session_factory() as session:
                session.query(CalendarEntryModel).filter(
                    CalendarEntryModel.id == str(saved.entry_id)
                ).delete(synchronize_session=False)
                session.commit()


def test_postgres_calendar_deliveries_due_and_claim(postgres_calendar_repo):
    repo, session_factory = postgres_calendar_repo
    now = datetime.now(timezone.utc)
    unique_suffix = uuid4().hex
    entry = None
    delivery = None

    try:
        entry = repo.save_entry(
            CalendarEntry.create(
                title=f"Postgres Due Delivery Test {unique_suffix}",
                entry_type=CalendarEntryType.ANNOUNCEMENT,
                creator_id=f"U_PG_CREATOR_{unique_suffix}",
                start_time=now + timedelta(hours=14),
                audience_type=CalendarAudienceType.INDIVIDUAL,
                audience_id=f"U_PG_RECIP_{unique_suffix}",
            )
        )

        delivery = repo.save_delivery(
            CalendarReminderDelivery.create(
                entry_id=entry.entry_id,
                recipient_id=f"U_PG_RECIP_{unique_suffix}",
                due_at=now - timedelta(minutes=5),  # Due now
            )
        )

        due = repo.find_due_deliveries(now=now)
        assert any(d.delivery_id == delivery.delivery_id for d in due)

        # Atomic claim
        assert repo.claim_due_delivery(delivery.delivery_id, now) is True
        # Concurrent claim must fail
        assert repo.claim_due_delivery(delivery.delivery_id, now) is False

        # Mark sent
        repo.mark_delivery_sent(delivery.delivery_id, now)
        updated = repo.find_delivery(delivery.delivery_id)
        assert updated.status == CalendarDeliveryStatus.SENT
    finally:
        with session_factory() as session:
            if delivery is not None:
                session.query(CalendarReminderDeliveryModel).filter(
                    CalendarReminderDeliveryModel.id == str(delivery.delivery_id)
                ).delete(synchronize_session=False)
            if entry is not None:
                session.query(CalendarEntryModel).filter(
                    CalendarEntryModel.id == str(entry.entry_id)
                ).delete(synchronize_session=False)
            session.commit()
