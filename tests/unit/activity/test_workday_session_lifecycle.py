from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import pytest

from domain.activity import (
    ActivityEvent,
    ActivityRepository,
    ActivitySource,
    ActivityType,
    InMemoryPersonPreferenceRepository,
    InMemoryWorkdaySessionRepository,
    PersonPreference,
    WorkdaySession,
    WorkdaySessionStatus,
)
from engines.slack.dto import SlackMessage
from application.activity import (
    ActivityDetector,
    ActivityProcessor,
    ActivityService,
    AttendanceCalculator,
)


class FakeActivityRepository(ActivityRepository):
    """In-memory fake ActivityRepository for testing."""

    def __init__(self) -> None:
        self.saved_events: list[ActivityEvent] = []

    def save(self, event: ActivityEvent) -> None:
        self.saved_events.append(event)

    def find_for_person(
        self,
        person_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ActivityEvent]:
        events = [e for e in self.saved_events if e.person_id == person_id]
        if start:
            events = [e for e in events if e.occurred_at >= start]
        if end:
            events = [e for e in events if e.occurred_at <= end]
        return events

    def find_people_by_name(self, person_name: str) -> list[ActivityEvent]:
        return [e for e in self.saved_events if e.person_name == person_name]

    def find_currently_on_break(self) -> list[ActivityEvent]:
        return []

    def find_currently_working(self) -> list[ActivityEvent]:
        return []

    def find_currently_off_work(self) -> list[ActivityEvent]:
        return []

    def find_latest_for_people(self) -> list[ActivityEvent]:
        return []


def _make_message(
    text: str,
    user: str = "U12345",
    user_name: str | None = "Alice",
    ts: str = "1762128000.100000",
    event_ts: str | None = None,
) -> SlackMessage:
    resolved_event_ts = event_ts if event_ts is not None else ts
    return SlackMessage(
        user=user,
        channel="CGENERAL",
        text=text,
        ts=ts,
        event_ts=resolved_event_ts,
        user_name=user_name,
    )


@pytest.fixture
def activity_repo() -> FakeActivityRepository:
    return FakeActivityRepository()


@pytest.fixture
def workday_repo() -> InMemoryWorkdaySessionRepository:
    return InMemoryWorkdaySessionRepository()


@pytest.fixture
def preference_repo() -> InMemoryPersonPreferenceRepository:
    return InMemoryPersonPreferenceRepository()


@pytest.fixture
def activity_service(
    activity_repo: FakeActivityRepository,
    workday_repo: InMemoryWorkdaySessionRepository,
    preference_repo: InMemoryPersonPreferenceRepository,
) -> ActivityService:
    return ActivityService(
        repository=activity_repo,
        attendance_calculator=AttendanceCalculator(),
        workday_session_repository=workday_repo,
        person_preference_repository=preference_repo,
        default_timezone="Asia/Kolkata",
    )


@pytest.fixture
def processor(
    activity_service: ActivityService,
    workday_repo: InMemoryWorkdaySessionRepository,
    preference_repo: InMemoryPersonPreferenceRepository,
) -> ActivityProcessor:
    return ActivityProcessor(
        detector=ActivityDetector(),
        activity_service=activity_service,
        workday_session_repository=workday_repo,
        person_preference_repository=preference_repo,
        default_timezone="Asia/Kolkata",
    )


def test_first_greeting_creates_one_active_session(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
    activity_repo: FakeActivityRepository,
) -> None:
    msg = _make_message("Good morning team!", user="U123", user_name="Alice", ts="1762128000.123")
    processor.process(msg)

    active = workday_repo.find_active("U123")
    assert active is not None
    assert active.person_id == "U123"
    assert active.person_name == "Alice"
    assert active.status == WorkdaySessionStatus.ACTIVE
    assert active.start_source_event_id == "1762128000.123"

    assert len(activity_repo.saved_events) == 1
    assert activity_repo.saved_events[0].activity_type == ActivityType.WORK_START


def test_repeated_greeting_does_not_create_duplicate(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
    activity_repo: FakeActivityRepository,
) -> None:
    msg1 = _make_message("Good morning", user="U123", user_name="Alice", ts="1762128000.000")
    processor.process(msg1)

    session_first = workday_repo.find_active("U123")
    assert session_first is not None
    initial_started_at = session_first.started_at

    # Second greeting arrives later
    msg2 = _make_message("Hi everyone", user="U123", user_name="Alice", ts="1762131600.000")
    processor.process(msg2)

    session_second = workday_repo.find_active("U123")
    assert session_second is not None
    assert session_second.identifier.graph_id == session_first.identifier.graph_id
    # Start timestamp must not be overwritten
    assert session_second.started_at == initial_started_at
    assert session_second.start_source_event_id == "1762128000.000"

    # Both messages recorded as activity events
    assert len(activity_repo.saved_events) == 2


def test_compound_greeting_creates_session_while_preserving_original_message(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
    activity_repo: FakeActivityRepository,
) -> None:
    text = "Good morning! Can you check the roadmap?"
    msg = _make_message(text, user="U123", user_name="Bob")
    processor.process(msg)

    active = workday_repo.find_active("U123")
    assert active is not None
    assert active.person_name == "Bob"

    assert len(activity_repo.saved_events) == 1
    event = activity_repo.saved_events[0]
    assert event.activity_type == ActivityType.WORK_START
    assert event.note == text


def test_explicit_work_start_creates_session(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
    activity_repo: FakeActivityRepository,
) -> None:
    msg = _make_message("starting work now", user="U456", user_name="Charlie")
    processor.process(msg)

    active = workday_repo.find_active("U456")
    assert active is not None
    assert active.person_id == "U456"
    assert active.person_name == "Charlie"
    assert active.status == WorkdaySessionStatus.ACTIVE


def test_explicit_signoff_closes_active_session(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
    activity_repo: FakeActivityRepository,
) -> None:
    start_msg = _make_message("starting work", user="U123", ts="1762128000.000", event_ts="1762128000.000")
    processor.process(start_msg)
    active = workday_repo.find_active("U123")
    assert active is not None

    end_msg = _make_message("signing off for today", user="U123", ts="1762156800.000", event_ts="1762156800.000")
    processor.process(end_msg)

    assert workday_repo.find_active("U123") is None
    latest = workday_repo.find_latest_for_person("U123")
    assert latest is not None
    assert latest.status == WorkdaySessionStatus.CLOSED
    assert latest.ended_at == datetime.fromtimestamp(1762156800.0, tz=timezone.utc)
    assert latest.end_source_event_id == "1762156800.000"


def test_repeated_signoff_is_idempotent(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    processor.process(_make_message("starting work", user="U123", ts="1762128000.000"))
    processor.process(_make_message("signing off", user="U123", ts="1762156800.000", event_ts="evt_end_1"))

    closed = workday_repo.find_latest_for_person("U123")
    assert closed is not None
    assert closed.status == WorkdaySessionStatus.CLOSED
    initial_ended_at = closed.ended_at

    # Repeated sign-off with same event_ts
    processor.process(_make_message("signing off", user="U123", ts="1762156800.000", event_ts="evt_end_1"))
    # Repeated sign-off with new event_ts
    processor.process(_make_message("done for today", user="U123", ts="1762160000.000", event_ts="evt_end_2"))

    assert workday_repo.find_active("U123") is None
    session_after = workday_repo.find_latest_for_person("U123")
    assert session_after is not None
    assert session_after.status == WorkdaySessionStatus.CLOSED
    assert session_after.ended_at == initial_ended_at


def test_ordinary_farewell_does_not_close_session(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    processor.process(_make_message("good morning", user="U123"))
    active = workday_repo.find_active("U123")
    assert active is not None

    processor.process(_make_message("bye team", user="U123"))
    processor.process(_make_message("see you tomorrow", user="U123"))
    processor.process(_make_message("goodbye", user="U123"))

    active_after = workday_repo.find_active("U123")
    assert active_after is not None
    assert active_after.status == WorkdaySessionStatus.ACTIVE
    assert active_after.ended_at is None


def test_new_shift_after_closure_creates_second_session_on_same_work_date(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    # Shift 1: morning
    processor.process(_make_message("starting work", user="U123", ts="1762135200.000", event_ts="evt_1"))
    processor.process(_make_message("done for the day", user="U123", ts="1762149600.000", event_ts="evt_2"))

    session1 = workday_repo.find_latest_for_person("U123")
    assert session1 is not None
    assert session1.status == WorkdaySessionStatus.CLOSED
    work_date = session1.work_date

    # Shift 2: evening on the same work date
    processor.process(_make_message("starting work", user="U123", ts="1762164000.000", event_ts="evt_3"))

    session2 = workday_repo.find_active("U123")
    assert session2 is not None
    assert session2.identifier.graph_id != session1.identifier.graph_id
    assert session2.work_date == work_date
    assert session2.status == WorkdaySessionStatus.ACTIVE

    sessions_today = workday_repo.find_for_person_on_date("U123", work_date)
    assert len(sessions_today) == 2


def test_person_preference_timezone_takes_precedence(
    activity_service: ActivityService,
    preference_repo: InMemoryPersonPreferenceRepository,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    preference_repo.save(
        PersonPreference.create(
            person_id="U123",
            preferred_timezone="Europe/London",
        )
    )

    mock_identity = MagicMock()
    mock_identity._directory = [{"id": "U123", "tz": "America/New_York"}]
    activity_service._identity_service = mock_identity

    session = activity_service.start_workday_session(
        person_id="U123",
        person_name="Alice",
        occurred_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )
    assert session is not None
    assert session.timezone == "Europe/London"


def test_invalid_preference_timezone_falls_back_safely(
    activity_service: ActivityService,
    preference_repo: InMemoryPersonPreferenceRepository,
) -> None:
    # Create preference with valid constructor then tamper preferred_timezone to invalid
    pref = PersonPreference.create(person_id="U123", preferred_timezone="UTC")
    pref.preferred_timezone = "Invalid/Nonexistent_Timezone"
    preference_repo.save(pref)

    # Cached directory has America/New_York
    mock_identity = MagicMock()
    mock_identity._directory = [{"id": "U123", "tz": "America/New_York"}]
    activity_service._identity_service = mock_identity

    resolved_tz = activity_service.resolve_timezone("U123")
    assert resolved_tz == "America/New_York"

    # If identity directory also has no tz, falls back to settings default (Asia/Kolkata)
    mock_identity._directory = []
    resolved_default = activity_service.resolve_timezone("U123")
    assert resolved_default == "Asia/Kolkata"


def test_local_work_date_derived_correctly_across_utc_date_boundaries(
    activity_service: ActivityService,
    preference_repo: InMemoryPersonPreferenceRepository,
) -> None:
    # 2026-11-02 23:30:00 UTC
    dt = datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc)

    # In Asia/Kolkata (+05:30), local is 2026-11-03 05:00:00 -> work_date = 2026-11-03
    preference_repo.save(
        PersonPreference.create(person_id="U_KOLKATA", preferred_timezone="Asia/Kolkata")
    )
    session_kolkata = activity_service.start_workday_session(
        person_id="U_KOLKATA",
        person_name="Rahul",
        occurred_at=dt,
    )
    assert session_kolkata is not None
    assert session_kolkata.work_date == date(2026, 11, 3)

    # In America/New_York (-05:00), local is 2026-11-02 18:30:00 -> work_date = 2026-11-02
    preference_repo.save(
        PersonPreference.create(person_id="U_NY", preferred_timezone="America/New_York")
    )
    session_ny = activity_service.start_workday_session(
        person_id="U_NY",
        person_name="Sarah",
        occurred_at=dt,
    )
    assert session_ny is not None
    assert session_ny.work_date == date(2026, 11, 2)


def test_missing_slack_timezone_does_not_cause_network_call(
    activity_service: ActivityService,
) -> None:
    mock_identity = MagicMock()
    mock_identity._directory = None  # Not yet cached

    activity_service._identity_service = mock_identity

    resolved = activity_service.resolve_timezone("U123")
    assert resolved == "Asia/Kolkata"
    mock_identity.get_workspace_users.assert_not_called()
    mock_identity.get_display_name.assert_not_called()
    mock_identity.resolve_user.assert_not_called()


def test_concurrent_active_session_conflict_rereads_repository(
    activity_service: ActivityService,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    original_save = workday_repo.save

    def concurrent_save(session: WorkdaySession) -> None:
        # Simulate another thread saving an active session just before this save
        concurrent_session = WorkdaySession.create(
            person_id=session.person_id,
            person_name=session.person_name,
            timezone=session.timezone,
            started_at=session.started_at,
            start_source_event_id="concurrent_evt",
        )
        original_save(concurrent_session)
        # Now raising the known duplicate active session error
        raise ValueError(
            f"Person '{session.person_id}' already has an active workday session."
        )

    workday_repo.save = concurrent_save  # type: ignore[assignment]

    result = activity_service.start_workday_session(
        person_id="U123",
        person_name="Alice",
        occurred_at=datetime.now(timezone.utc),
        source_event_id="my_evt",
    )

    assert result is not None
    assert result.person_id == "U123"
    assert result.start_source_event_id == "concurrent_evt"
    assert workday_repo.find_active("U123") is not None


def test_unrelated_repository_errors_propagate(
    activity_service: ActivityService,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    def failing_save(session: WorkdaySession) -> None:
        raise RuntimeError("Database connection dropped unexpectedly.")

    workday_repo.save = failing_save  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Database connection dropped unexpectedly"):
        activity_service.start_workday_session(
            person_id="U123",
            person_name="Alice",
            occurred_at=datetime.now(timezone.utc),
        )


def test_existing_activity_event_and_break_tracking_intact(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
    activity_repo: FakeActivityRepository,
) -> None:
    # 1. Start work
    processor.process(_make_message("starting work", user="U123", ts="1762128000.000", event_ts="e1"))
    assert len(activity_repo.saved_events) == 1
    assert activity_repo.saved_events[0].activity_type == ActivityType.WORK_START
    active = workday_repo.find_active("U123")
    assert active is not None

    # 2. Break start
    processor.process(_make_message("taking a break", user="U123", ts="1762131600.000", event_ts="e2"))
    assert len(activity_repo.saved_events) == 2
    assert activity_repo.saved_events[1].activity_type == ActivityType.BREAK_START
    # Session must still be active and unchanged
    active_during_break = workday_repo.find_active("U123")
    assert active_during_break is not None
    assert active_during_break.status == WorkdaySessionStatus.ACTIVE

    # 3. Break end
    processor.process(_make_message("back to work", user="U123", ts="1762133400.000", event_ts="e3"))
    assert len(activity_repo.saved_events) == 3
    assert activity_repo.saved_events[2].activity_type == ActivityType.BREAK_END
    # Session still active
    active_after_break = workday_repo.find_active("U123")
    assert active_after_break is not None
    assert active_after_break.status == WorkdaySessionStatus.ACTIVE

    # 4. Sign off
    processor.process(_make_message("signing off", user="U123", ts="1762156800.000", event_ts="e4"))
    assert len(activity_repo.saved_events) == 4
    assert activity_repo.saved_events[3].activity_type == ActivityType.WORK_END
    # Session is now closed
    assert workday_repo.find_active("U123") is None
    latest = workday_repo.find_latest_for_person("U123")
    assert latest is not None
    assert latest.status == WorkdaySessionStatus.CLOSED


def test_user_name_fallback_to_user_id(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    # user_name is None
    processor.process(_make_message("starting work", user="U_NO_NAME", user_name=None))
    active = workday_repo.find_active("U_NO_NAME")
    assert active is not None
    assert active.person_name == "U_NO_NAME"

    # user_name is empty string / whitespace
    processor.process(_make_message("starting work", user="U_BLANK_NAME", user_name="   "))
    active2 = workday_repo.find_active("U_BLANK_NAME")
    assert active2 is not None
    assert active2.person_name == "U_BLANK_NAME"


def test_invalid_timestamp_falls_back_to_utc_now(
    processor: ActivityProcessor,
    workday_repo: InMemoryWorkdaySessionRepository,
) -> None:
    before = datetime.now(timezone.utc)
    processor.process(_make_message("starting work", user="U_BAD_TS", ts="not-a-timestamp", event_ts="also-bad"))
    after = datetime.now(timezone.utc)

    active = workday_repo.find_active("U_BAD_TS")
    assert active is not None
    assert before <= active.started_at <= after
