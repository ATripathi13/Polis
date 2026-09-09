from __future__ import annotations

from datetime import datetime, timezone
from .attendance_calculator import AttendanceCalculator
from .attendance_result import AttendanceResult
from domain.activity import (
    ActivityEvent,
    ActivityRepository,
    ActivitySource,
    ActivityType,
)


class ActivityService:
    """
    Application-facing service for recording and querying activity events.
    """

    def __init__(
        self,
        repository: ActivityRepository,
        attendance_calculator: AttendanceCalculator,
    ) -> None:
        self._repository = repository
        self._attendance_calculator = attendance_calculator

    def record(
        self,
        *,
        person_id: str,
        person_name: str,
        activity_type: ActivityType,
        occurred_at: datetime,
        source: ActivitySource,
        source_event_id: str | None = None,
        break_type: str | None = None,
        note: str | None = None,
    ) -> ActivityEvent:

        event = ActivityEvent.create(
            person_id=person_id,
            person_name=person_name,
            activity_type=activity_type,
            occurred_at=occurred_at,
            source=source,
            source_event_id=source_event_id,
            break_type=break_type,
            note=note,
        )

        self._repository.save(event)

        return event

    def find_for_person(
        self,
        person_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ActivityEvent]:

        return self._repository.find_for_person(
            person_id,
            start=start,
            end=end,
        )
    def find_people_by_name(
        self,
        person_name: str,
    ) -> list[ActivityEvent]:

        return self._repository.find_people_by_name(
            person_name,
        )        
    def find_for_person_by_name(
        self,
        person_name: str,
    ) -> list[ActivityEvent]:
        return self._repository.find_people_by_name(
            person_name,
        )
    def calculate_attendance(
        self,
        person_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        now: datetime | None = None,
    ) -> AttendanceResult | None:

        events = self.find_for_person(
            person_id,
            start=start,
            end=end,
        )

        if not events:
            return None

        calculation_time = now or datetime.now(
            timezone.utc,
        )

        return self._attendance_calculator.calculate(
            events=events,
            now=calculation_time,
        )
    def calculate_attendance_for_person_name(
        self,
        person_name: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        now: datetime | None = None,
    ) -> list[AttendanceResult]:
        people = self.find_people_by_name(person_name)

        results: list[AttendanceResult] = []

        for person in people:
            result = self.calculate_attendance(
                person.person_id,
                start=start,
                end=end,
                now=now,
            )

            if result is not None:
                results.append(result)

        return results
    def find_currently_on_break(
        self,
    ) -> list[ActivityEvent]:
        """
        Return people whose latest activity event
        indicates that they are currently on break.
        """

        return self._repository.find_currently_on_break()

    def find_currently_working(
        self,
    ) -> list[ActivityEvent]:
        """
        Return people whose latest activity event
        indicates that they are currently working.
        """

        return self._repository.find_currently_working()

    def find_currently_off_work(
        self,
    ) -> list[ActivityEvent]:
        """
        Return people whose latest activity event
        indicates that they are currently off work.
        """

        return self._repository.find_currently_off_work()