from datetime import datetime, timezone
from unittest.mock import Mock

from application.activity.activity_question_service import ActivityQuestionService
from domain.activity import ActivityType
from domain.activity.aggregates.activity_event import ActivityEvent
from domain.activity.enums.activity_source import ActivitySource
from domain.reasoning import Question
from datetime import datetime, timedelta, timezone
from application.activity.attendance_calculator import AttendanceCalculator

def make_event(
    person_id: str,
    person_name: str,
    activity_type: ActivityType,
    occurred_at: datetime,
) -> ActivityEvent:
    return ActivityEvent.create(
        person_id=person_id,
        person_name=person_name,
        activity_type=activity_type,
        occurred_at=occurred_at,
        source=ActivitySource.SLACK,
        source_event_id=f"{person_id}-{occurred_at.timestamp()}",
    )

def create_service(events, now=None):
    activity_service = Mock()

    activity_service.find_people_by_name.return_value = [
        events[-1]
    ]

    activity_service.find_for_person_by_name.return_value = [
        events[-1]
    ]

    activity_service.find_for_person.return_value = events

    calculator = AttendanceCalculator()

    def calculate_attendance(
        person_id,
        *,
        start=None,
        end=None,
        now=None,
    ):
        return calculator.calculate(
            events=events,
            now=now or datetime.now(timezone.utc),
        )

    activity_service.calculate_attendance.side_effect = (
        calculate_attendance
    )

    return ActivityQuestionService(
        activity_service=activity_service,
        now_provider=(
            lambda: now
            if now is not None
            else datetime.now(timezone.utc)
        ),
    )

def test_when_person_started_work():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
    ]

    service = create_service(events)
    answer = service.answer(
        Question(text="When did Akshat start work?")
    )

    assert "Akshat" in answer.text
    assert start.isoformat() in answer.text


def test_when_person_went_on_break():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = datetime(
        2026,
        9,
        9,
        11,
        30,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_START,
            break_start,
        ),
    ]

    service = create_service(events)

    answer = service.answer(
        Question(text="When did Akshat go on break?")
    )

    assert "Akshat" in answer.text
    assert break_start.isoformat() in answer.text


def test_when_person_came_back():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = datetime(
        2026,
        9,
        9,
        11,
        30,
        tzinfo=timezone.utc,
    )

    break_end = datetime(
        2026,
        9,
        9,
        11,
        45,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_START,
            break_start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_END,
            break_end,
        ),
    ]

    service = create_service(events)

    answer = service.answer(
        Question(text="When did Akshat come back?")
    )

    assert "Akshat" in answer.text
    assert break_end.isoformat() in answer.text


def test_when_person_finished_work():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026,
        9,
        9,
        17,
        0,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_END,
            end,
        ),
    ]

    service = create_service(events)

    answer = service.answer(
        Question(text="When did Akshat finish work?")
    )

    assert "Akshat" in answer.text
    assert end.isoformat() in answer.text

def test_how_much_work_person_did_today():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = datetime(
        2026,
        9,
        9,
        11,
        0,
        tzinfo=timezone.utc,
    )

    break_end = datetime(
        2026,
        9,
        9,
        11,
        30,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026,
        9,
        9,
        17,
        0,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_START,
            break_start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_END,
            break_end,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_END,
            end,
        ),
    ]

    service = create_service(
        events,
        now=end,
    )

    answer = service.answer(
        Question(text="How much did Akshat work today?")
    )

    assert "Akshat" in answer.text
    assert "7 hours 30 minutes" in answer.text


def test_how_much_break_time_person_took_today():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = datetime(
        2026,
        9,
        9,
        11,
        0,
        tzinfo=timezone.utc,
    )

    break_end = datetime(
        2026,
        9,
        9,
        11,
        30,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026,
        9,
        9,
        17,
        0,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_START,
            break_start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_END,
            break_end,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_END,
            end,
        ),
    ]

    service = create_service(
        events,
        now=end,
    )

    answer = service.answer(
        Question(text="How much break time did Akshat take today?")
    )

    assert "Akshat" in answer.text
    assert "30 minutes" in answer.text


def test_how_long_person_has_been_working():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    now = datetime(
        2026,
        9,
        9,
        12,
        0,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
    ]

    service = create_service(
        events,
        now=now,
    )

    answer = service.answer(
        Question(text="How long has Akshat been working?")
    )

    assert "Akshat" in answer.text
    assert "3 hours" in answer.text


def test_how_long_person_has_been_on_break():
    start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    break_start = datetime(
        2026,
        9,
        9,
        11,
        0,
        tzinfo=timezone.utc,
    )

    now = datetime(
        2026,
        9,
        9,
        11,
        20,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_START,
            break_start,
        ),
    ]

    service = create_service(
        events,
        now=now,
    )

    answer = service.answer(
        Question(text="How long has Akshat been on break?")
    )

    assert "Akshat" in answer.text
    assert "20 minutes" in answer.text


def test_timestamp_question_uses_latest_event_today():
    yesterday_start = datetime(
        2026,
        9,
        8,
        9,
        0,
        tzinfo=timezone.utc,
    )

    yesterday_end = datetime(
        2026,
        9,
        8,
        17,
        0,
        tzinfo=timezone.utc,
    )

    today_start = datetime(
        2026,
        9,
        9,
        10,
        0,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            yesterday_start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_END,
            yesterday_end,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            today_start,
        ),
    ]

    service = create_service(
        events,
        now=datetime(
            2026,
            9,
            9,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    answer = service.answer(
        Question(text="When did Akshat start work?")
    )

    assert today_start.isoformat() in answer.text
    assert yesterday_start.isoformat() not in answer.text


def test_timestamp_question_uses_latest_break_today():
    work_start = datetime(
        2026,
        9,
        9,
        9,
        0,
        tzinfo=timezone.utc,
    )

    first_break = datetime(
        2026,
        9,
        9,
        11,
        0,
        tzinfo=timezone.utc,
    )

    first_return = datetime(
        2026,
        9,
        9,
        11,
        20,
        tzinfo=timezone.utc,
    )

    second_break = datetime(
        2026,
        9,
        9,
        15,
        0,
        tzinfo=timezone.utc,
    )

    second_return = datetime(
        2026,
        9,
        9,
        15,
        15,
        tzinfo=timezone.utc,
    )

    events = [
        make_event(
            "U123",
            "Akshat",
            ActivityType.WORK_START,
            work_start,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_START,
            first_break,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_END,
            first_return,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_START,
            second_break,
        ),
        make_event(
            "U123",
            "Akshat",
            ActivityType.BREAK_END,
            second_return,
        ),
    ]

    service = create_service(
        events,
        now=datetime(
            2026,
            9,
            9,
            16,
            0,
            tzinfo=timezone.utc,
        ),
    )

    answer = service.answer(
        Question(text="When did Akshat go on break?")
    )

    assert second_break.isoformat() in answer.text
    assert first_break.isoformat() not in answer.text