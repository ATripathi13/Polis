from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..aggregates import ActivityEvent


class ActivityRepository(ABC):
    """
    Repository for observed activity events.
    """

    @abstractmethod
    def save(
        self,
        event: ActivityEvent,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_for_person(
        self,
        person_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ActivityEvent]:
        raise NotImplementedError

    @abstractmethod
    def find_people_by_name(
        self,
        person_name: str,
    ) -> list[ActivityEvent]:
        """
        Return activity records for people whose
        persisted Slack name matches the supplied name.
        """
        raise NotImplementedError

    @abstractmethod
    def find_currently_on_break(
        self,
    ) -> list[ActivityEvent]:
        """
        Return the latest activity event for each person
        whose current state is break_start.
        """
        raise NotImplementedError
    @abstractmethod
    def find_currently_working(
        self,
    ) -> list[ActivityEvent]:
        raise NotImplementedError

    @abstractmethod
    def find_currently_off_work(
        self,
    ) -> list[ActivityEvent]:
        raise NotImplementedError

    @abstractmethod
    def find_latest_for_people(
        self,
    ) -> list[ActivityEvent]:
        raise NotImplementedError