"""
Unit tests for InMemoryWorkdaySessionRepository.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from domain.activity import (
    InMemoryWorkdaySessionRepository,
    WorkdaySession,
    WorkdaySessionStatus,
)
from domain.common.identifier import Identifier


def make_session(
    person_id: str = "U100",
    work_date: date | None = None,
    started_at: datetime | None = None,
    status: WorkdaySessionStatus = WorkdaySessionStatus.ACTIVE,
    ended_at: datetime | None = None,
    created_at: datetime | None = None,
    identifier: Identifier | None = None,
) -> WorkdaySession:
    d = work_date or date(2026, 11, 2)
    s = started_at or datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    e = ended_at
    if status in (WorkdaySessionStatus.CLOSED, WorkdaySessionStatus.ABANDONED) and e is None:
        e = s + timedelta(hours=8)

    return WorkdaySession(
        identifier=identifier or Identifier(),
        person_id=person_id,
        person_name=f"Person {person_id}",
        work_date=d,
        status=status,
        started_at=s,
        ended_at=e,
        timezone="UTC",
        created_at=created_at,
    )


# =====================================================================
# 1. Insert and Update
# =====================================================================


def test_save_and_retrieve_session():
    repo = InMemoryWorkdaySessionRepository()
    session = make_session(person_id="U100")

    repo.save(session)

    found = repo.find_active("U100")
    assert found is not None
    assert found.identifier == session.identifier
    assert found.person_id == "U100"


def test_save_updates_existing_session():
    repo = InMemoryWorkdaySessionRepository()
    session = make_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)
    repo.save(session)

    session.update_durations(work_minutes=120, break_minutes=15)
    repo.save(session)

    found = repo.find_active("U100")
    assert found is not None
    assert found.total_work_minutes == 120
    assert found.total_break_minutes == 15


# =====================================================================
# 2. Concurrency & Active Session Constraints
# =====================================================================


def test_re_saving_same_active_session_succeeds():
    repo = InMemoryWorkdaySessionRepository()
    session = make_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)

    repo.save(session)
    # Re-saving the identical active session must succeed without raising
    repo.save(session)

    assert repo.find_active("U100") is session


def test_rejects_second_active_session_for_same_person():
    repo = InMemoryWorkdaySessionRepository()
    session1 = make_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)
    session2 = make_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)

    repo.save(session1)

    with pytest.raises(ValueError, match="already has an active workday session"):
        repo.save(session2)


def test_different_people_active_sessions_do_not_conflict():
    repo = InMemoryWorkdaySessionRepository()
    session1 = make_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)
    session2 = make_session(person_id="U200", status=WorkdaySessionStatus.ACTIVE)

    repo.save(session1)
    repo.save(session2)

    assert repo.find_active("U100") is session1
    assert repo.find_active("U200") is session2


# =====================================================================
# 3. Multiple Closed/Abandoned Sessions & Split Shifts
# =====================================================================


def test_allows_multiple_closed_and_abandoned_sessions_for_same_person():
    repo = InMemoryWorkdaySessionRepository()
    target_date = date(2026, 11, 2)

    session1 = make_session(
        person_id="U100",
        work_date=target_date,
        started_at=datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )
    session2 = make_session(
        person_id="U100",
        work_date=target_date,
        started_at=datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.ABANDONED,
    )
    session3 = make_session(
        person_id="U100",
        work_date=date(2026, 11, 3),
        started_at=datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )

    repo.save(session1)
    repo.save(session2)
    repo.save(session3)

    on_date = repo.find_for_person_on_date("U100", target_date)
    assert len(on_date) == 2
    assert on_date[0] is session1
    assert on_date[1] is session2


def test_split_shifts_returned_in_chronological_order():
    repo = InMemoryWorkdaySessionRepository()
    target_date = date(2026, 11, 2)

    # Save shifts out of order
    evening_shift = make_session(
        person_id="U100",
        work_date=target_date,
        started_at=datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )
    morning_shift = make_session(
        person_id="U100",
        work_date=target_date,
        started_at=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )
    afternoon_shift = make_session(
        person_id="U100",
        work_date=target_date,
        started_at=datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.ACTIVE,
    )
    other_person_shift = make_session(
        person_id="U200",
        work_date=target_date,
        started_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )

    repo.save(evening_shift)
    repo.save(morning_shift)
    repo.save(afternoon_shift)
    repo.save(other_person_shift)

    shifts = repo.find_for_person_on_date("U100", target_date)
    assert len(shifts) == 3
    assert shifts[0] is morning_shift
    assert shifts[1] is afternoon_shift
    assert shifts[2] is evening_shift


# =====================================================================
# 4. find_latest_for_person() Ordering and Tie-Breaking
# =====================================================================


def test_find_latest_orders_by_started_at_desc():
    repo = InMemoryWorkdaySessionRepository()
    s1 = make_session(
        person_id="U100",
        started_at=datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )
    s2 = make_session(
        person_id="U100",
        started_at=datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.ACTIVE,
    )
    s3 = make_session(
        person_id="U100",
        started_at=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )

    repo.save(s1)
    repo.save(s2)
    repo.save(s3)

    latest = repo.find_latest_for_person("U100")
    assert latest is s2


def test_find_latest_tie_breaks_on_created_at_desc():
    repo = InMemoryWorkdaySessionRepository()
    same_started_at = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    s_older = make_session(
        person_id="U100",
        started_at=same_started_at,
        created_at=datetime(2026, 11, 2, 10, 0, 1, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )
    s_newer = make_session(
        person_id="U100",
        started_at=same_started_at,
        created_at=datetime(2026, 11, 2, 10, 0, 5, tzinfo=timezone.utc),
        status=WorkdaySessionStatus.CLOSED,
    )

    repo.save(s_older)
    repo.save(s_newer)

    latest = repo.find_latest_for_person("U100")
    assert latest is s_newer


def test_find_latest_returns_none_when_empty():
    repo = InMemoryWorkdaySessionRepository()
    assert repo.find_latest_for_person("U_UNKNOWN") is None


def test_find_active_returns_none_when_no_active_session():
    repo = InMemoryWorkdaySessionRepository()
    closed = make_session(person_id="U100", status=WorkdaySessionStatus.CLOSED)
    repo.save(closed)

    assert repo.find_active("U100") is None
    assert repo.find_active("U_UNKNOWN") is None


# =====================================================================
# 5. Validation on Invalid person_id
# =====================================================================


@pytest.mark.parametrize("invalid_id", ["", "   ", None, 123, []])
def test_rejects_invalid_person_id_on_queries(invalid_id):
    repo = InMemoryWorkdaySessionRepository()

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_active(invalid_id)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_latest_for_person(invalid_id)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_for_person_on_date(invalid_id, date(2026, 11, 2))  # type: ignore[arg-type]
