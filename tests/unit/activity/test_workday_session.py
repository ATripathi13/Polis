"""
Unit tests for the WorkdaySession domain aggregate.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from domain.activity import WorkdaySession, WorkdaySessionStatus
from domain.common.identifier import Identifier


STARTED_AT = datetime(2026, 11, 2, 9, 0, 0, tzinfo=timezone.utc)


# =====================================================================
# 1. Factory and Initialization
# =====================================================================


def test_create_active_session_with_explicit_work_date():
    explicit_date = date(2026, 11, 2)
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="America/New_York",
        work_date=explicit_date,
        start_source_event_id="slack-evt-1",
    )

    assert session.person_id == "U12345"
    assert session.person_name == "Alice Smith"
    assert session.work_date == explicit_date
    assert session.timezone == "America/New_York"
    assert session.started_at == STARTED_AT
    assert session.status == WorkdaySessionStatus.ACTIVE
    assert session.ended_at is None
    assert session.briefing_sent_at is None
    assert session.total_work_minutes == 0
    assert session.total_break_minutes == 0
    assert session.start_source_event_id == "slack-evt-1"
    assert session.end_source_event_id is None
    assert session.is_active is True
    assert session.is_closed is False
    assert session.is_abandoned is False


def test_create_derives_work_date_from_local_timezone():
    # 2026-11-02 02:00:00 UTC is 2026-11-01 22:00:00 in America/New_York (UTC-4)
    early_utc = datetime(2026, 11, 2, 2, 0, 0, tzinfo=timezone.utc)
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=early_utc,
        timezone="America/New_York",
    )

    assert session.work_date == date(2026, 11, 1)


def test_create_derives_work_date_across_date_boundary_in_asia_kolkata():
    # 2026-11-02 23:30:00 UTC is 2026-11-03 05:00:00 in Asia/Kolkata (UTC+5:30)
    late_utc = datetime(2026, 11, 2, 23, 30, 0, tzinfo=timezone.utc)
    session = WorkdaySession.create(
        person_id="U67890",
        person_name="Bob Jones",
        started_at=late_utc,
        timezone="Asia/Kolkata",
    )

    assert session.work_date == date(2026, 11, 3)


def test_create_preserves_optional_identifier_and_metadata():
    metadata = {"channel": "C123", "role": "engineer"}
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
        business_id="sess-custom-001",
        metadata=metadata,
    )

    assert session.business_id == "sess-custom-001"
    assert session.metadata == metadata
    assert isinstance(session.graph_id, UUID)


def test_constructor_initialization_with_explicit_identifier_and_timestamps():
    ident = Identifier(business_id="explicit-id")
    created = datetime(2026, 11, 2, 8, 55, tzinfo=timezone.utc)
    updated = datetime(2026, 11, 2, 8, 59, tzinfo=timezone.utc)

    session = WorkdaySession(
        identifier=ident,
        person_id="U12345",
        person_name="Alice Smith",
        work_date=date(2026, 11, 2),
        started_at=STARTED_AT,
        timezone="UTC",
        created_at=created,
        updated_at=updated,
    )

    assert session.identifier == ident
    assert session.business_id == "explicit-id"
    assert session.created_at == created
    assert session.updated_at == updated


# =====================================================================
# 2. Validation
# =====================================================================


@pytest.mark.parametrize("blank_id", ["", "   ", None])
def test_rejects_blank_person_id(blank_id):
    with pytest.raises(ValueError, match="person_id cannot be empty"):
        WorkdaySession.create(
            person_id=blank_id,
            person_name="Alice Smith",
            started_at=STARTED_AT,
            timezone="UTC",
        )


@pytest.mark.parametrize("blank_name", ["", "   ", None])
def test_rejects_blank_person_name(blank_name):
    with pytest.raises(ValueError, match="person_name cannot be empty"):
        WorkdaySession.create(
            person_id="U12345",
            person_name=blank_name,
            started_at=STARTED_AT,
            timezone="UTC",
        )


@pytest.mark.parametrize("blank_tz", ["", "   ", None])
def test_rejects_blank_timezone(blank_tz):
    with pytest.raises(ValueError, match="timezone cannot be empty"):
        WorkdaySession.create(
            person_id="U12345",
            person_name="Alice Smith",
            started_at=STARTED_AT,
            timezone=blank_tz,
        )


@pytest.mark.parametrize("invalid_tz", ["Mars/Olympus", "Invalid/Timezone", "NotATimezone"])
def test_rejects_invalid_iana_timezone(invalid_tz):
    with pytest.raises(ValueError, match="Invalid timezone"):
        WorkdaySession.create(
            person_id="U12345",
            person_name="Alice Smith",
            started_at=STARTED_AT,
            timezone=invalid_tz,
        )


def test_rejects_naive_started_at():
    naive_start = datetime(2026, 11, 2, 9, 0)
    with pytest.raises(ValueError, match="started_at must be timezone-aware"):
        WorkdaySession.create(
            person_id="U12345",
            person_name="Alice Smith",
            started_at=naive_start,
            timezone="UTC",
        )


def test_rejects_naive_ended_at_in_constructor():
    naive_end = datetime(2026, 11, 2, 17, 0)
    with pytest.raises(ValueError, match="ended_at must be timezone-aware"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=date(2026, 11, 2),
            started_at=STARTED_AT,
            timezone="UTC",
            ended_at=naive_end,
        )


def test_rejects_naive_briefing_sent_at_in_constructor():
    naive_briefing = datetime(2026, 11, 2, 9, 5)
    with pytest.raises(ValueError, match="briefing_sent_at must be timezone-aware"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=date(2026, 11, 2),
            started_at=STARTED_AT,
            timezone="UTC",
            briefing_sent_at=naive_briefing,
        )


def test_rejects_datetime_passed_as_work_date():
    dt_as_date = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="work_date must be a date, not a datetime"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=dt_as_date,
            started_at=STARTED_AT,
            timezone="UTC",
        )


def test_rejects_ended_at_earlier_than_started_at():
    earlier_end = STARTED_AT - timedelta(hours=1)
    with pytest.raises(ValueError, match="ended_at cannot precede started_at"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=date(2026, 11, 2),
            started_at=STARTED_AT,
            timezone="UTC",
            ended_at=earlier_end,
        )


def test_rejects_negative_durations_in_constructor():
    with pytest.raises(ValueError, match="total_work_minutes cannot be negative"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=date(2026, 11, 2),
            started_at=STARTED_AT,
            timezone="UTC",
            total_work_minutes=-1,
        )

    with pytest.raises(ValueError, match="total_break_minutes cannot be negative"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=date(2026, 11, 2),
            started_at=STARTED_AT,
            timezone="UTC",
            total_break_minutes=-15,
        )


def test_rejects_closed_status_without_ended_at():
    with pytest.raises(ValueError, match="Session in status 'closed' must have ended_at"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=date(2026, 11, 2),
            started_at=STARTED_AT,
            timezone="UTC",
            status=WorkdaySessionStatus.CLOSED,
            ended_at=None,
        )


def test_rejects_abandoned_status_without_ended_at():
    with pytest.raises(ValueError, match="Session in status 'abandoned' must have ended_at"):
        WorkdaySession(
            person_id="U12345",
            person_name="Alice Smith",
            work_date=date(2026, 11, 2),
            started_at=STARTED_AT,
            timezone="UTC",
            status=WorkdaySessionStatus.ABANDONED,
            ended_at=None,
        )


# =====================================================================
# 3. close()
# =====================================================================


def test_close_active_session_successfully():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    initial_updated_at = session.updated_at
    ended_at = STARTED_AT + timedelta(hours=8)

    session.close(
        ended_at,
        end_source_event_id="slack-end-evt",
        total_work_minutes=420,
        total_break_minutes=60,
    )

    assert session.status == WorkdaySessionStatus.CLOSED
    assert session.is_closed is True
    assert session.is_active is False
    assert session.ended_at == ended_at
    assert session.end_source_event_id == "slack-end-evt"
    assert session.total_work_minutes == 420
    assert session.total_break_minutes == 60
    assert session.updated_at >= initial_updated_at


def test_close_rejects_already_closed_session():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    ended_at = STARTED_AT + timedelta(hours=8)
    session.close(ended_at)

    with pytest.raises(ValueError, match="Only ACTIVE sessions can be closed"):
        session.close(ended_at + timedelta(hours=1))


def test_close_rejects_already_abandoned_session():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    session.abandon()

    with pytest.raises(ValueError, match="Only ACTIVE sessions can be closed"):
        session.close(STARTED_AT + timedelta(hours=8))


def test_close_invalid_arguments_do_not_partially_mutate():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )

    # 1. Naive ended_at
    naive_end = datetime(2026, 11, 2, 17, 0)
    with pytest.raises(ValueError, match="ended_at must be timezone-aware"):
        session.close(naive_end, total_work_minutes=300)
    assert session.is_active is True
    assert session.ended_at is None
    assert session.total_work_minutes == 0

    # 2. ended_at earlier than started_at
    with pytest.raises(ValueError, match="ended_at cannot precede started_at"):
        session.close(STARTED_AT - timedelta(minutes=5), total_work_minutes=300)
    assert session.is_active is True
    assert session.ended_at is None
    assert session.total_work_minutes == 0

    # 3. Negative work minutes
    valid_end = STARTED_AT + timedelta(hours=8)
    with pytest.raises(ValueError, match="total_work_minutes cannot be negative"):
        session.close(valid_end, total_work_minutes=-50)
    assert session.is_active is True
    assert session.ended_at is None
    assert session.total_work_minutes == 0

    # 4. Negative break minutes
    with pytest.raises(ValueError, match="total_break_minutes cannot be negative"):
        session.close(valid_end, total_break_minutes=-10)
    assert session.is_active is True
    assert session.ended_at is None
    assert session.total_break_minutes == 0


# =====================================================================
# 4. abandon()
# =====================================================================


def test_abandon_active_session_with_default_timestamp():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )

    session.abandon()

    assert session.status == WorkdaySessionStatus.ABANDONED
    assert session.is_abandoned is True
    assert session.is_active is False
    assert session.ended_at is not None
    assert session.ended_at.tzinfo is not None
    assert session.ended_at >= session.started_at


def test_abandon_active_session_with_explicit_timestamp():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    explicit_end = STARTED_AT + timedelta(hours=4)

    session.abandon(ended_at=explicit_end)

    assert session.ended_at == explicit_end
    assert session.is_abandoned is True


def test_abandon_stores_non_empty_reason_in_metadata():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )

    session.abandon(reason="Network disconnected unexpectedly")

    assert session.metadata.get("abandon_reason") == "Network disconnected unexpectedly"


@pytest.mark.parametrize("empty_reason", [None, "", "   "])
def test_abandon_empty_reason_does_not_set_metadata(empty_reason):
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )

    session.abandon(reason=empty_reason)

    assert "abandon_reason" not in session.metadata


def test_abandon_rejects_already_closed_or_abandoned_session():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    session.close(STARTED_AT + timedelta(hours=8))

    with pytest.raises(ValueError, match="Only ACTIVE sessions can be abandoned"):
        session.abandon()

    session_abandoned = WorkdaySession.create(
        person_id="U67890",
        person_name="Bob Jones",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    session_abandoned.abandon()

    with pytest.raises(ValueError, match="Only ACTIVE sessions can be abandoned"):
        session_abandoned.abandon()


def test_abandon_invalid_arguments_do_not_partially_mutate():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )

    # 1. Naive ended_at
    naive_end = datetime(2026, 11, 2, 12, 0)
    with pytest.raises(ValueError, match="ended_at must be timezone-aware"):
        session.abandon(reason="Lost power", ended_at=naive_end)
    assert session.is_active is True
    assert session.ended_at is None
    assert "abandon_reason" not in session.metadata

    # 2. ended_at earlier than started_at
    with pytest.raises(ValueError, match="ended_at cannot precede started_at"):
        session.abandon(
            reason="Lost power",
            ended_at=STARTED_AT - timedelta(minutes=15),
        )
    assert session.is_active is True
    assert session.ended_at is None
    assert "abandon_reason" not in session.metadata


# =====================================================================
# 5. Briefing and Duration Updates
# =====================================================================


def test_record_briefing_sent_with_default_and_explicit_timestamps():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    initial_updated = session.updated_at

    # Default timestamp
    session.record_briefing_sent()
    assert session.briefing_sent_at is not None
    assert session.briefing_sent_at.tzinfo is not None
    assert session.updated_at >= initial_updated

    # Explicit timestamp
    custom_sent = STARTED_AT + timedelta(minutes=12)
    session.record_briefing_sent(sent_at=custom_sent)
    assert session.briefing_sent_at == custom_sent


def test_record_briefing_sent_rejects_naive_timestamp_without_mutation():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    naive_sent = datetime(2026, 11, 2, 9, 15)

    with pytest.raises(ValueError, match="sent_at must be timezone-aware"):
        session.record_briefing_sent(sent_at=naive_sent)

    assert session.briefing_sent_at is None


def test_update_durations_with_valid_values():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    initial_updated = session.updated_at

    session.update_durations(work_minutes=180, break_minutes=30)

    assert session.total_work_minutes == 180
    assert session.total_break_minutes == 30
    assert session.updated_at >= initial_updated


def test_update_durations_atomicity_on_negative_values():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    session.update_durations(work_minutes=120, break_minutes=25)

    # 1. Negative work minutes
    with pytest.raises(ValueError, match="work_minutes cannot be negative"):
        session.update_durations(work_minutes=-10, break_minutes=40)
    assert session.total_work_minutes == 120
    assert session.total_break_minutes == 25

    # 2. Negative break minutes
    with pytest.raises(ValueError, match="break_minutes cannot be negative"):
        session.update_durations(work_minutes=200, break_minutes=-5)
    # work_minutes must not be partially set to 200
    assert session.total_work_minutes == 120
    assert session.total_break_minutes == 25


# =====================================================================
# 6. State Properties
# =====================================================================


def test_lifecycle_properties_reflect_status():
    session = WorkdaySession.create(
        person_id="U12345",
        person_name="Alice Smith",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    assert session.is_active is True
    assert session.is_closed is False
    assert session.is_abandoned is False

    session.close(STARTED_AT + timedelta(hours=8))
    assert session.is_active is False
    assert session.is_closed is True
    assert session.is_abandoned is False

    session_abandoned = WorkdaySession.create(
        person_id="U67890",
        person_name="Bob Jones",
        started_at=STARTED_AT,
        timezone="UTC",
    )
    session_abandoned.abandon()
    assert session_abandoned.is_active is False
    assert session_abandoned.is_closed is False
    assert session_abandoned.is_abandoned is True
