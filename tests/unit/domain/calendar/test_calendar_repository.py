"""
Unit tests for CalendarRepository (tested using InMemoryCalendarRepository).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from domain.calendar import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntry,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderDelivery,
    InMemoryCalendarRepository,
)


@pytest.fixture
def repo() -> InMemoryCalendarRepository:
    return InMemoryCalendarRepository()


def test_save_and_find_entry(repo):
    start = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    entry = CalendarEntry.create(
        title="Architecture Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U1",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_id="U1",
    )

    repo.save_entry(entry)
    retrieved = repo.find_entry(entry.entry_id)

    assert retrieved is not None
    assert retrieved.entry_id == entry.entry_id
    assert retrieved.title == "Architecture Sync"
    assert retrieved.entry_type == CalendarEntryType.ACTIVITY


def test_list_entries_filtering(repo):
    t1 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)

    e1 = repo.save_entry(
        CalendarEntry.create(
            title="Activity 1",
            entry_type=CalendarEntryType.ACTIVITY,
            creator_id="U1",
            start_time=t1,
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id="U1",
        )
    )
    e2 = repo.save_entry(
        CalendarEntry.create(
            title="Holiday 2",
            entry_type=CalendarEntryType.HOLIDAY,
            creator_id="U1",
            start_time=t2,
            audience_type=CalendarAudienceType.ORGANIZATION,
            audience_id="organization",
        )
    )
    e3 = repo.save_entry(
        CalendarEntry.create(
            title="Announcement 3",
            entry_type=CalendarEntryType.ANNOUNCEMENT,
            creator_id="U2",
            start_time=t3,
            audience_type=CalendarAudienceType.TEAM,
            audience_id="dev-team",
        )
    )

    # Date range filter
    range_results = repo.list_entries(start_range=t1, end_range=t2)
    assert len(range_results) == 2
    assert {e.entry_id for e in range_results} == {e1.entry_id, e2.entry_id}

    # Type filter
    holidays = repo.list_entries(entry_type=CalendarEntryType.HOLIDAY)
    assert len(holidays) == 1
    assert holidays[0].entry_id == e2.entry_id

    # Audience filter
    team_entries = repo.list_entries(
        audience_type=CalendarAudienceType.TEAM,
        audience_id="dev-team",
    )
    assert len(team_entries) == 1
    assert team_entries[0].entry_id == e3.entry_id


def test_find_due_deliveries_and_atomic_claim(repo):
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    past_due = now - timedelta(hours=1)
    future_due = now + timedelta(hours=2)

    d_past = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id="ENTRY-1",
            recipient_id="U1",
            due_at=past_due,
        )
    )
    d_future = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id="ENTRY-2",
            recipient_id="U2",
            due_at=future_due,
        )
    )

    due = repo.find_due_deliveries(now=now)
    assert len(due) == 1
    assert due[0].delivery_id == d_past.delivery_id

    # Atomic claim: first claim succeeds
    claim_time = datetime.now(timezone.utc)
    assert repo.claim_due_delivery(d_past.delivery_id, claim_time) is True

    # Second concurrent claim on the same delivery must fail
    assert repo.claim_due_delivery(d_past.delivery_id, claim_time) is False

    # Delivery is no longer returned as pending due
    due_after_claim = repo.find_due_deliveries(now=now)
    assert len(due_after_claim) == 0


def test_delivery_status_updates(repo):
    due = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    d = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id="ENTRY-1",
            recipient_id="U1",
            due_at=due,
        )
    )

    sent_at = datetime.now(timezone.utc)
    repo.mark_delivery_sent(d.delivery_id, sent_at)
    updated = repo.find_delivery(d.delivery_id)
    assert updated.status == CalendarDeliveryStatus.SENT
    assert updated.sent_at == sent_at

    # Failure update
    d2 = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id="ENTRY-2",
            recipient_id="U2",
            due_at=due,
        )
    )
    fail_time = datetime.now(timezone.utc)
    repo.mark_delivery_failed(d2.delivery_id, "Slack channel not found", fail_time)
    updated2 = repo.find_delivery(d2.delivery_id)
    assert updated2.status == CalendarDeliveryStatus.FAILED
    assert updated2.error_message == "Slack channel not found"


def test_cancel_pending_deliveries_for_entry(repo):
    due = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    d1 = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id="ENTRY-CANCEL",
            recipient_id="U1",
            due_at=due,
        )
    )
    d2 = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id="ENTRY-CANCEL",
            recipient_id="U2",
            due_at=due,
        )
    )
    d_other = repo.save_delivery(
        CalendarReminderDelivery.create(
            entry_id="ENTRY-OTHER",
            recipient_id="U3",
            due_at=due,
        )
    )

    cancelled_count = repo.cancel_pending_deliveries_for_entry("ENTRY-CANCEL")
    assert cancelled_count == 2

    assert repo.find_delivery(d1.delivery_id).status == CalendarDeliveryStatus.CANCELLED
    assert repo.find_delivery(d2.delivery_id).status == CalendarDeliveryStatus.CANCELLED
    assert repo.find_delivery(d_other.delivery_id).status == CalendarDeliveryStatus.PENDING
