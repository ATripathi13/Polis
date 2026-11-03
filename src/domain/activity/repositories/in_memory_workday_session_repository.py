from __future__ import annotations

from datetime import date
import threading

from ..aggregates.workday_session import WorkdaySession
from ..enums.workday_session_status import WorkdaySessionStatus
from .workday_session_repository import WorkdaySessionRepository


class InMemoryWorkdaySessionRepository(WorkdaySessionRepository):
    """
    In-memory thread-safe implementation of WorkdaySessionRepository.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, WorkdaySession] = {}
        self._lock = threading.Lock()

    def save(
        self,
        session: WorkdaySession,
    ) -> None:
        key = str(session.identifier.graph_id)
        with self._lock:
            if session.status == WorkdaySessionStatus.ACTIVE:
                for existing in self._sessions.values():
                    if (
                        existing.person_id == session.person_id
                        and existing.status == WorkdaySessionStatus.ACTIVE
                        and str(existing.identifier.graph_id) != key
                    ):
                        raise ValueError(
                            f"Person '{session.person_id}' already has an active workday session."
                        )

            self._sessions[key] = session

    def find_active(
        self,
        person_id: str,
    ) -> WorkdaySession | None:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._lock:
            for session in self._sessions.values():
                if (
                    session.person_id == person_id
                    and session.status == WorkdaySessionStatus.ACTIVE
                ):
                    return session
            return None

    def find_latest_for_person(
        self,
        person_id: str,
    ) -> WorkdaySession | None:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._lock:
            matching = [
                s for s in self._sessions.values()
                if s.person_id == person_id
            ]
            if not matching:
                return None

            matching.sort(
                key=lambda s: (s.started_at, s.created_at),
                reverse=True,
            )
            return matching[0]

    def find_for_person_on_date(
        self,
        person_id: str,
        work_date: date,
    ) -> list[WorkdaySession]:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        with self._lock:
            matching = [
                s for s in self._sessions.values()
                if s.person_id == person_id and s.work_date == work_date
            ]
            matching.sort(key=lambda s: s.started_at)
            return list(matching)
