from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo
from .attendance_calculator import AttendanceCalculator
from .attendance_result import AttendanceResult
from domain.activity import (
    ActivityEvent,
    ActivityRepository,
    ActivitySource,
    ActivityType,
    PersonPreferenceRepository,
    WorkdaySession,
    WorkdaySessionRepository,
)


class ActivityService:
    """
    Application-facing service for recording and querying activity events
    and coordinating workday session lifecycles.
    """

    def __init__(
        self,
        repository: ActivityRepository,
        attendance_calculator: AttendanceCalculator,
        workday_session_repository: WorkdaySessionRepository | None = None,
        person_preference_repository: PersonPreferenceRepository | None = None,
        default_timezone: str | None = None,
        identity_service: Any | None = None,
    ) -> None:
        self._repository = repository
        self._attendance_calculator = attendance_calculator
        self._workday_session_repository = workday_session_repository
        self._person_preference_repository = person_preference_repository
        self._default_timezone = default_timezone
        self._identity_service = identity_service

    @property
    def repository(self) -> ActivityRepository:
        return self._repository

    @property
    def workday_session_repository(self) -> WorkdaySessionRepository | None:
        return self._workday_session_repository

    @property
    def person_preference_repository(self) -> PersonPreferenceRepository | None:
        return self._person_preference_repository

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

    def resolve_timezone(self, person_id: str) -> str:
        """
        Resolve timezone in precedence order:
        1. PersonPreference.preferred_timezone
        2. Slack directory timezone, if an existing cached identity lookup is available
        3. settings.calendar_default_timezone
        4. UTC safety fallback

        No Slack APIs or network calls are made. Timezone is validated with ZoneInfo.
        """
        # 1. PersonPreference.preferred_timezone
        if self._person_preference_repository is not None:
            try:
                pref = self._person_preference_repository.get_or_default(person_id)
                if pref is not None and pref.preferred_timezone:
                    tz_candidate = str(pref.preferred_timezone).strip()
                    try:
                        ZoneInfo(tz_candidate)
                        return tz_candidate
                    except Exception:
                        pass
            except Exception:
                pass

        # 2. Slack directory timezone, if an existing cached identity lookup is available
        if self._identity_service is not None:
            cached_directory = getattr(self._identity_service, "_directory", None)
            if cached_directory and isinstance(cached_directory, list):
                for user in cached_directory:
                    if isinstance(user, dict) and user.get("id") == person_id:
                        tz_candidate = user.get("tz")
                        if tz_candidate and isinstance(tz_candidate, str) and tz_candidate.strip():
                            try:
                                clean_tz = tz_candidate.strip()
                                ZoneInfo(clean_tz)
                                return clean_tz
                            except Exception:
                                pass
                        break

        # 3. settings.calendar_default_timezone or configured default_timezone
        candidate_default = self._default_timezone
        if not candidate_default:
            try:
                from infrastructure.config.settings import get_settings
                candidate_default = get_settings().calendar_default_timezone
            except Exception:
                candidate_default = "Asia/Kolkata"

        if candidate_default and isinstance(candidate_default, str) and candidate_default.strip():
            try:
                clean_tz = candidate_default.strip()
                ZoneInfo(clean_tz)
                return clean_tz
            except Exception:
                pass

        # 4. UTC safety fallback
        return "UTC"

    def start_workday_session(
        self,
        *,
        person_id: str,
        person_name: str,
        occurred_at: datetime,
        source_event_id: str | None = None,
    ) -> WorkdaySession | None:
        """
        Coordinate starting a workday session.

        - If no WorkdaySessionRepository is configured, returns None.
        - Checks find_active(person_id). If an active session exists, returns it without creating another.
        - Resolves timezone, derives work_date, creates WorkdaySession aggregate, and saves it.
        - Concurrency: If save raises the known active-session ValueError, re-reads find_active(person_id)
          and returns the active session if one exists.
        - Unrelated errors propagate.
        """
        if self._workday_session_repository is None:
            return None

        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = occurred_at.astimezone(timezone.utc)

        # Idempotency: if active session exists, do not create another or overwrite start timestamp
        active = self._workday_session_repository.find_active(person_id)
        if active is not None:
            return active

        resolved_tz = self.resolve_timezone(person_id)
        work_date = occurred_at.astimezone(ZoneInfo(resolved_tz)).date()

        session = WorkdaySession.create(
            person_id=person_id,
            person_name=person_name,
            timezone=resolved_tz,
            work_date=work_date,
            started_at=occurred_at,
            start_source_event_id=source_event_id,
        )

        try:
            self._workday_session_repository.save(session)
            return session
        except ValueError as exc:
            if "already has an active workday session" in str(exc):
                active = self._workday_session_repository.find_active(person_id)
                if active is not None:
                    return active
            raise

    def sign_off_workday_session(
        self,
        *,
        person_id: str,
        occurred_at: datetime,
        source_event_id: str | None = None,
    ) -> WorkdaySession | None:
        """
        Coordinate explicit sign-off for a workday session.

        - If no WorkdaySessionRepository is configured, returns None.
        - Finds the active session for the person. If none exists, returns None (no-op).
        - If the session's end_source_event_id matches source_event_id, treat as duplicate.
        - Otherwise closes the session and saves through WorkdaySessionRepository.
        """
        if self._workday_session_repository is None:
            return None

        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = occurred_at.astimezone(timezone.utc)

        active = self._workday_session_repository.find_active(person_id)
        if active is None:
            return None

        # Duplicate event check
        if source_event_id is not None and active.end_source_event_id == source_event_id:
            return active

        active.close(
            ended_at=occurred_at,
            end_source_event_id=source_event_id,
        )
        self._workday_session_repository.save(active)
        return active

    def find_active_workday_session(
        self,
        person_id: str,
    ) -> WorkdaySession | None:
        """
        Return the currently active workday session for person_id, or None.
        """
        if self._workday_session_repository is None:
            return None
        return self._workday_session_repository.find_active(person_id)