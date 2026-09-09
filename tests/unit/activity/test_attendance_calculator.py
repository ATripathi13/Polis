from datetime import datetime, timedelta, timezone
from uuid import uuid4

from application.activity.attendance_calculator import (
    AttendanceCalculator,
)
from domain.activity import (
    ActivityEvent,
    ActivitySource,
    ActivityType,
)


def make_event(
    activity_type: ActivityType,
    occurred_at: datetime,
) -> ActivityEvent:
    return ActivityEvent(
        person_id="U_TEST",
        person_name="Test User",
        activity_type=activity_type,
        occurred_at=occurred_at,
        source=ActivitySource.SLACK,
        source_event_id=str(uuid4()),
        created_at=occurred_at,
    )


def test_work_start_then_break_then_break_end():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = start + timedelta(hours=2)

    break_end = break_start + timedelta(minutes=15)

    now = break_end + timedelta(hours=1)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_START,
            break_start,
        ),
        make_event(
            ActivityType.BREAK_END,
            break_end,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.work_started_at == start
    assert result.current_state == "working"
    assert result.total_break_duration == timedelta(minutes=15)
    assert result.active_work_duration == timedelta(hours=3)


def test_work_end_marks_person_off_work():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    end = start + timedelta(hours=8)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.WORK_END,
            end,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=end + timedelta(hours=1),
    )

    assert result.work_started_at == start
    assert result.work_ended_at == end
    assert result.current_state == "off_work"
    assert result.active_work_duration == timedelta(hours=8)


def test_break_after_work_end_does_not_reopen_work_session():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    work_end = start + timedelta(hours=8)

    invalid_break_start = work_end + timedelta(minutes=30)

    invalid_break_end = invalid_break_start + timedelta(minutes=10)

    now = invalid_break_end + timedelta(hours=1)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.WORK_END,
            work_end,
        ),
        make_event(
            ActivityType.BREAK_START,
            invalid_break_start,
        ),
        make_event(
            ActivityType.BREAK_END,
            invalid_break_end,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.work_started_at == start
    assert result.work_ended_at == work_end
    assert result.current_state == "off_work"
    assert result.active_work_duration == timedelta(hours=8)

def test_multiple_work_sessions_in_same_day():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    lunch_start = start + timedelta(hours=3)
    lunch_end = lunch_start + timedelta(minutes=30)

    first_work_end = start + timedelta(hours=4)

    second_work_start = start + timedelta(hours=5)
    second_work_end = start + timedelta(hours=8)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_START,
            lunch_start,
        ),
        make_event(
            ActivityType.BREAK_END,
            lunch_end,
        ),
        make_event(
            ActivityType.WORK_END,
            first_work_end,
        ),
        make_event(
            ActivityType.WORK_START,
            second_work_start,
        ),
        make_event(
            ActivityType.WORK_END,
            second_work_end,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=second_work_end + timedelta(hours=1),
    )

    assert result.work_started_at == start
    assert result.work_ended_at == second_work_end
    assert result.total_break_duration == timedelta(minutes=30)
    assert result.active_work_duration == timedelta(hours=6, minutes=30)
    assert result.current_state == "off_work"

def test_active_break_is_counted_until_now():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = start + timedelta(hours=2)

    now = break_start + timedelta(hours=1)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_START,
            break_start,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.work_started_at == start
    assert result.current_state == "on_break"
    assert result.total_break_duration == timedelta(hours=1)
    assert result.active_work_duration == timedelta(hours=2)

    assert result.current_break is not None
    assert result.current_break.started_at == break_start
    assert result.current_break.ended_at is None

def test_break_end_without_break_start_does_not_create_break():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_end = start + timedelta(hours=2)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_END,
            break_end,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=break_end + timedelta(hours=1),
    )

    assert result.work_started_at == start
    assert result.current_state == "working"
    assert result.total_break_duration == timedelta(0)
    assert result.active_work_duration == timedelta(hours=3)
    assert result.current_break is None
    assert result.breaks == []

def test_duplicate_work_start_does_not_double_count_work():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    duplicate_start = start + timedelta(minutes=5)

    now = start + timedelta(hours=3)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.WORK_START,
            duplicate_start,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.work_started_at == start
    assert result.current_state == "working"
    assert result.active_work_duration == timedelta(hours=3)
    assert result.total_break_duration == timedelta(0)

def test_duplicate_break_start_does_not_restart_break():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    first_break_start = start + timedelta(hours=2)
    duplicate_break_start = first_break_start + timedelta(minutes=5)

    now = first_break_start + timedelta(hours=1)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_START,
            first_break_start,
        ),
        make_event(
            ActivityType.BREAK_START,
            duplicate_break_start,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.work_started_at == start
    assert result.current_state == "on_break"
    assert result.total_break_duration == timedelta(hours=1)
    assert result.active_work_duration == timedelta(hours=2)

    assert result.current_break is not None
    assert result.current_break.started_at == first_break_start
    assert result.current_break.ended_at is None


def test_duplicate_break_end_does_not_create_extra_break():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = start + timedelta(hours=2)
    break_end = break_start + timedelta(minutes=15)
    duplicate_break_end = break_end + timedelta(minutes=5)

    now = duplicate_break_end + timedelta(hours=1)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_START,
            break_start,
        ),
        make_event(
            ActivityType.BREAK_END,
            break_end,
        ),
        make_event(
            ActivityType.BREAK_END,
            duplicate_break_end,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.work_started_at == start
    assert result.current_state == "working"
    assert result.total_break_duration == timedelta(minutes=15)
    assert result.active_work_duration == timedelta(hours=3, minutes=5)

    assert len(result.breaks) == 1
    assert result.current_break is None


def test_multiple_breaks_are_all_counted():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_one_start = start + timedelta(hours=2)
    break_one_end = break_one_start + timedelta(minutes=15)

    break_two_start = start + timedelta(hours=4)
    break_two_end = break_two_start + timedelta(minutes=30)

    work_end = start + timedelta(hours=8)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_START,
            break_one_start,
        ),
        make_event(
            ActivityType.BREAK_END,
            break_one_end,
        ),
        make_event(
            ActivityType.BREAK_START,
            break_two_start,
        ),
        make_event(
            ActivityType.BREAK_END,
            break_two_end,
        ),
        make_event(
            ActivityType.WORK_END,
            work_end,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=work_end + timedelta(hours=1),
    )

    assert result.work_started_at == start
    assert result.work_ended_at == work_end
    assert result.current_state == "off_work"

    assert result.total_break_duration == timedelta(minutes=45)
    assert result.active_work_duration == timedelta(hours=7, minutes=15)

    assert len(result.breaks) == 2

    assert result.breaks[0].started_at == break_one_start
    assert result.breaks[0].ended_at == break_one_end

    assert result.breaks[1].started_at == break_two_start
    assert result.breaks[1].ended_at == break_two_end

    assert result.current_break is None

def test_active_work_duration_continues_until_now():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    now = start + timedelta(hours=3, minutes=30)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.current_state == "working"
    assert result.work_started_at == start
    assert result.work_ended_at is None
    assert result.active_work_duration == timedelta(hours=3, minutes=30)
    assert result.total_break_duration == timedelta(0)

def test_active_break_duration_continues_until_now():
    start = datetime(
        2026,
        9,
        7,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = start + timedelta(hours=2)
    now = break_start + timedelta(hours=1, minutes=30)

    events = [
        make_event(
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            ActivityType.BREAK_START,
            break_start,
        ),
    ]

    result = AttendanceCalculator().calculate(
        events=events,
        now=now,
    )

    assert result.current_state == "on_break"
    assert result.work_started_at == start
    assert result.work_ended_at is None

    assert result.total_break_duration == timedelta(hours=1, minutes=30)
    assert result.active_work_duration == timedelta(hours=2)

    assert result.current_break is not None
    assert result.current_break.started_at == break_start
    assert result.current_break.ended_at is None
    assert result.current_break.duration(now=now) == timedelta(hours=1, minutes=30)