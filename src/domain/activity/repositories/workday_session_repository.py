from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..aggregates.workday_session import WorkdaySession


class WorkdaySessionRepository(ABC):
    """
    Repository contract for WorkdaySession aggregate persistence.
    """

    @abstractmethod
    def save(
        self,
        session: WorkdaySession,
    ) -> None:
        """
        Persist a new or modified WorkdaySession aggregate.

        Implementations must enforce that at most one ACTIVE session exists per person_id.
        """
        raise NotImplementedError

    @abstractmethod
    def find_active(
        self,
        person_id: str,
    ) -> WorkdaySession | None:
        """
        Return the currently ACTIVE session for the person, or None if no
        session is currently active.
        """
        raise NotImplementedError

    @abstractmethod
    def find_latest_for_person(
        self,
        person_id: str,
    ) -> WorkdaySession | None:
        """
        Return the most recent session for the person, ordered by
        started_at DESC, tie-breaking on created_at DESC. Returns None if
        no sessions exist for the person.
        """
        raise NotImplementedError

    @abstractmethod
    def find_for_person_on_date(
        self,
        person_id: str,
        work_date: date,
    ) -> list[WorkdaySession]:
        """
        Return all split-shift sessions for a person on a specific local
        work date, ordered chronologically by started_at ASC.
        """
        raise NotImplementedError
