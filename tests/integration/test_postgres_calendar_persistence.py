"""
Integration tests for PostgreSQLCalendarRepository with isolated test database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.calendar import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntry,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderDelivery,
)
from infrastructure.database import calendar_repository as calendar_module
from infrastructure.database.calendar_repository import PostgreSQLCalendarRepository
from infrastructure.database.models import (
    Base,
    CalendarEntryModel,
    CalendarReminderDeliveryModel,
)


@pytest.fixture
def postgres_calendar_repo(monkeypatch):
    """Use only the explicitly configured isolated polis_test database."""
    database_url = os.environ.get("POLIS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set POLIS_TEST_DATABASE_URL to the isolated polis_test URL.")

    if not database_url.startswith("postgresql+psycopg://"):
        pytest.fail("POLIS_TEST_DATABASE_URL must use postgresql+psycopg://")

    from sqlalchemy.engine import make_url

    parsed_url = make_url(database_url)
    if parsed_url.host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail("POLIS_TEST_DATABASE_URL must point to a local PostgreSQL host.")
    if parsed_url.database != "polis_test":
        pytest.fail("POLIS_TEST_DATABASE_URL must target the 'polis_test' database.")

    engine = create_engine(database_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            database_name = connection.exec_driver_sql(
                "SELECT current_database()"
            ).scalar_one()

        if database_name != "polis_test":
            pytest.fail(
                f"Refusing to write to database {database_name!r}; "
                "expected 'polis_test'."
            )

        Base.metadata.create_all(bind=engine)

        TestSessionLocal = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
        )

        monkeypatch.setattr(
            calendar_module, "SessionLocal", TestSessionLocal
        )

        yield PostgreSQLCalendarRepository(), TestSessionLocal
    finally:
        engine.dispose()


def test_postgres_calendar_entry_roundtrip(postgres_calendar_repo):
    repo, _ = postgres_calendar_repo
    now = datetime.now(timezone.utc)
    entry = CalendarEntry.create(
        title="Postgres Integration Test Event",
        description="Verifying PostgreSQL persistence",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_PG_TEST",
        start_time=now + timedelta(days=1),
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_id="U_PG_TARGET",
    )

    saved = repo.save_entry(entry)
    retrieved = repo.find_entry(saved.entry_id)

    assert retrieved is not None
    assert retrieved.entry_id == saved.entry_id
    assert retrieved.title == "Postgres Integration Test Event"
    assert retrieved.entry_type == CalendarEntryType.ACTIVITY
    assert retrieved.creator_id == "U_PG_TEST"


def test_postgres_calendar_deliveries_due_and_claim(postgres_calendar_repo):
    repo, _ = postgres_calendar_repo
    now = datetime.now(timezone.utc)
    entry = repo.save_entry(
        CalendarEntry.create(
            title="Postgres Due Delivery Test",
            entry_type=CalendarEntryType.ANNOUNCEMENT,
            creator_id="U_PG_CREATOR",
            start_time=now + timedelta(hours=14),
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id="U_PG_RECIP",
        )
    )

    delivery = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id=entry.entry_id,
            recipient_id="U_PG_RECIP",
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
