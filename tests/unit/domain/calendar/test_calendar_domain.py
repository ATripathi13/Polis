"""
Unit tests for Calendar domain entities, enums, exceptions, and value objects.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from domain.calendar import (
    CalendarAudience,
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntry,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderDelivery,
    CalendarReminderPolicy,
    InvalidCalendarEntryError,
    InvalidTimeRangeError,
)


def test_calendar_entry_types_and_statuses():
    """Verify supported entry types and statuses match specification."""
    assert CalendarEntryType.ACTIVITY.value == "activity"
    assert CalendarEntryType.HOLIDAY.value == "holiday"
    assert CalendarEntryType.ANNOUNCEMENT.value == "announcement"

    assert CalendarEntryStatus.SCHEDULED.value == "scheduled"
    assert CalendarEntryStatus.CANCELLED.value == "cancelled"
    assert CalendarEntryStatus.COMPLETED.value == "completed"

    assert CalendarDeliveryStatus.PENDING.value == "pending"
    assert CalendarDeliveryStatus.PROCESSING.value == "processing"
    assert CalendarDeliveryStatus.SENT.value == "sent"
    assert CalendarDeliveryStatus.FAILED.value == "failed"
    assert CalendarDeliveryStatus.CANCELLED.value == "cancelled"


def test_calendar_reminder_policy_exact_15_hours():
    """Verify default reminder policy calculates due time exactly 15 hours before start."""
    policy = CalendarReminderPolicy(offset_hours=15)
    assert policy.offset_hours == 15

    # Test with UTC
    start_utc = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    due_utc = policy.calculate_due_time(start_utc)
    assert due_utc == datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)
    assert start_utc - due_utc == timedelta(hours=15)

    # Test with Asia/Kolkata
    tz_kolkata = ZoneInfo("Asia/Kolkata")
    start_kolkata = datetime(2026, 11, 10, 10, 0, tzinfo=tz_kolkata)
    due_kolkata = policy.calculate_due_time(start_kolkata)
    assert due_kolkata == datetime(2026, 11, 9, 19, 0, tzinfo=tz_kolkata)
    assert start_kolkata - due_kolkata == timedelta(hours=15)


def test_calendar_reminder_policy_validation():
    """Ensure invalid policy parameters are rejected."""
    with pytest.raises(ValueError, match="greater than zero"):
        CalendarReminderPolicy(offset_hours=0)

    with pytest.raises(ValueError, match="greater than zero"):
        CalendarReminderPolicy(offset_hours=-5)

    policy = CalendarReminderPolicy(offset_hours=15)
    naive_dt = datetime(2026, 11, 10, 10, 0)
    with pytest.raises(InvalidTimeRangeError, match="must be timezone-aware"):
        policy.calculate_due_time(naive_dt)


def test_calendar_entry_creation_and_validation():
    """Verify entry creation succeeds with valid data and rejects invalid invariants."""
    tz = ZoneInfo("Asia/Kolkata")
    start_time = datetime(2026, 12, 1, 9, 0, tzinfo=tz)
    end_time = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = CalendarEntry.create(
        title="Q4 All-Hands",
        description="Company-wide quarterly review",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U12345",
        start_time=start_time,
        end_time=end_time,
        timezone_name="Asia/Kolkata",
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_id="organization",
    )

    assert entry.title == "Q4 All-Hands"
    assert entry.entry_type == CalendarEntryType.ACTIVITY
    assert entry.creator_id == "U12345"
    assert entry.start_time == start_time
    assert entry.end_time == end_time
    assert entry.timezone == "Asia/Kolkata"
    assert entry.version == 1
    assert entry.status == CalendarEntryStatus.SCHEDULED


def test_calendar_entry_rejects_empty_title():
    tz = timezone.utc
    start = datetime(2026, 12, 1, 9, 0, tzinfo=tz)

    with pytest.raises(InvalidCalendarEntryError, match="title cannot be empty"):
        CalendarEntry.create(
            title="   ",
            entry_type=CalendarEntryType.ACTIVITY,
            creator_id="U123",
            start_time=start,
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id="U123",
        )


def test_calendar_entry_rejects_empty_creator():
    tz = timezone.utc
    start = datetime(2026, 12, 1, 9, 0, tzinfo=tz)

    with pytest.raises(InvalidCalendarEntryError, match="creator cannot be empty"):
        CalendarEntry.create(
            title="Design Review",
            entry_type=CalendarEntryType.ACTIVITY,
            creator_id="",
            start_time=start,
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id="U123",
        )


def test_calendar_entry_rejects_naive_datetime():
    with pytest.raises(InvalidTimeRangeError, match="must be timezone-aware"):
        CalendarEntry.create(
            title="Design Review",
            entry_type=CalendarEntryType.ACTIVITY,
            creator_id="U123",
            start_time=datetime(2026, 12, 1, 9, 0),  # Naive
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id="U123",
        )


def test_calendar_entry_rejects_end_time_before_start_time():
    tz = timezone.utc
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)
    end = datetime(2026, 12, 1, 9, 0, tzinfo=tz)

    with pytest.raises(InvalidTimeRangeError, match="End time cannot precede start time"):
        CalendarEntry.create(
            title="Design Review",
            entry_type=CalendarEntryType.ACTIVITY,
            creator_id="U123",
            start_time=start,
            end_time=end,
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id="U123",
        )


def test_calendar_entry_rejects_invalid_timezone():
    tz = timezone.utc
    start = datetime(2026, 12, 1, 9, 0, tzinfo=tz)

    with pytest.raises(InvalidTimeRangeError, match="Invalid timezone"):
        CalendarEntry.create(
            title="Design Review",
            entry_type=CalendarEntryType.ACTIVITY,
            creator_id="U123",
            start_time=start,
            timezone_name="Invalid/Timezone_Name",
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id="U123",
        )


def test_calendar_entry_reschedule_and_versioning():
    tz = timezone.utc
    start = datetime(2026, 12, 1, 9, 0, tzinfo=tz)
    entry = CalendarEntry.create(
        title="Weekly Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U123",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_id="U123",
    )
    assert entry.version == 1

    new_start = datetime(2026, 12, 2, 14, 0, tzinfo=tz)
    entry.reschedule(new_start_time=new_start)
    assert entry.version == 2
    assert entry.start_time == new_start


def test_calendar_entry_cancellation():
    tz = timezone.utc
    start = datetime(2026, 12, 1, 9, 0, tzinfo=tz)
    entry = CalendarEntry.create(
        title="Cancelled Holiday",
        entry_type=CalendarEntryType.HOLIDAY,
        creator_id="U123",
        start_time=start,
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_id="organization",
    )
    assert entry.status == CalendarEntryStatus.SCHEDULED

    entry.cancel()
    assert entry.status == CalendarEntryStatus.CANCELLED

    # Cannot reschedule cancelled entry
    with pytest.raises(InvalidCalendarEntryError, match="Cannot reschedule a cancelled"):
        entry.reschedule(new_start_time=datetime(2026, 12, 2, 9, 0, tzinfo=tz))


def test_calendar_entry_visibility():
    tz = timezone.utc
    start = datetime(2026, 12, 1, 9, 0, tzinfo=tz)

    # Individual entry
    indiv_entry = CalendarEntry.create(
        title="1-on-1",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_id="U_TARGET",
    )
    assert indiv_entry.is_visible_to("U_CREATOR") is True
    assert indiv_entry.is_visible_to("U_TARGET") is True
    assert indiv_entry.is_visible_to("U_OTHER") is False

    # Team entry
    team_entry = CalendarEntry.create(
        title="Team Standup",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.TEAM,
        audience_id="backend-team",
    )
    assert team_entry.is_visible_to("U_CREATOR") is True
    assert team_entry.is_visible_to("U_MEMBER", user_team_ids=["backend-team"]) is True
    assert team_entry.is_visible_to("U_OTHER", user_team_ids=["frontend-team"]) is False

    # Org entry
    org_entry = CalendarEntry.create(
        title="Holiday",
        entry_type=CalendarEntryType.HOLIDAY,
        creator_id="U_HR",
        start_time=start,
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_id="organization",
    )
    assert org_entry.is_visible_to("U_ANYONE") is True


def test_calendar_reminder_delivery_lifecycle():
    due = datetime(2026, 11, 30, 18, 0, tzinfo=timezone.utc)
    delivery = CalendarReminderDelivery.create(
        entry_id="ENTRY-123",
        recipient_id="U_TARGET",
        delivery_channel="dm",
        version=1,
        due_at=due,
    )
    assert delivery.status == CalendarDeliveryStatus.PENDING
    assert delivery.attempt_count == 0
    assert delivery.idempotency_key == "cal-rem:ENTRY-123:U_TARGET:v1"

    # Mark processing
    delivery.mark_processing()
    assert delivery.status == CalendarDeliveryStatus.PROCESSING
    assert delivery.attempt_count == 1
    assert delivery.last_attempt_at is not None

    # Mark failed
    delivery.mark_failed("Rate limit exceeded")
    assert delivery.status == CalendarDeliveryStatus.FAILED
    assert delivery.error_message == "Rate limit exceeded"

    # Mark sent
    delivery.mark_sent()
    assert delivery.status == CalendarDeliveryStatus.SENT
    assert delivery.sent_at is not None
    assert delivery.error_message is None
