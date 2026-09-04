from __future__ import annotations

from datetime import datetime

from ..aggregates import ActivityEvent
from ..enums import ActivitySource, ActivityType
from ..repositories import ActivityRepository


class ActivityService:
    """
    Application-facing service for recording and querying activity events.
    """

    def __init__(
        self,
        repository: ActivityRepository,
    ) -> None:
        self._repository = repository

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

    def find_latest_for_people(
        self,
    ) -> list[ActivityEvent]:
        return self._repository.find_latest_for_people()

    def find_currently_on_break(
        self,
    ) -> list[ActivityEvent]:
        return self._repository.find_currently_on_break()


    def find_currently_working(
        self,
    ) -> list[ActivityEvent]:
        return self._repository.find_currently_working()


    def find_currently_off_work(
        self,
    ) -> list[ActivityEvent]:
        return self._repository.find_currently_off_work()