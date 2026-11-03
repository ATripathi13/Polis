from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from domain.common.aggregate import AggregateRoot
from domain.common.identifier import Identifier

from ..enums.workday_session_status import WorkdaySessionStatus


class WorkdaySession(AggregateRoot):
    """
    Aggregate root representing a discrete daily work session for a person.

    Tracks attendance duration, briefing delivery, source provenance,
    and lifecycle transitions (ACTIVE -> CLOSED or ABANDONED).
    """

    def __init__(
        self,
        *,
        person_id: str,
        person_name: str,
        work_date: date,
        started_at: datetime,
        timezone: str,
        status: WorkdaySessionStatus = WorkdaySessionStatus.ACTIVE,
        ended_at: datetime | None = None,
        briefing_sent_at: datetime | None = None,
        total_work_minutes: int = 0,
        total_break_minutes: int = 0,
        start_source_event_id: str | None = None,
        end_source_event_id: str | None = None,
        identifier: Identifier | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__(
            identifier=identifier or Identifier(),
            metadata=dict(metadata or {}),
        )

        if created_at is not None:
            self.created_at = created_at
        if updated_at is not None:
            self.updated_at = updated_at

        if not person_id or not person_id.strip():
            raise ValueError("person_id cannot be empty.")

        if not person_name or not person_name.strip():
            raise ValueError("person_name cannot be empty.")

        if not timezone or not timezone.strip():
            raise ValueError("timezone cannot be empty.")

        try:
            ZoneInfo(timezone)
        except Exception as err:
            raise ValueError(f"Invalid timezone: {timezone}") from err

        if started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware (UTC).")

        if ended_at is not None:
            if ended_at.tzinfo is None:
                raise ValueError("ended_at must be timezone-aware (UTC).")
            if ended_at < started_at:
                raise ValueError("ended_at cannot precede started_at.")

        if briefing_sent_at is not None and briefing_sent_at.tzinfo is None:
            raise ValueError("briefing_sent_at must be timezone-aware (UTC).")

        if isinstance(work_date, datetime) or not isinstance(work_date, date):
            raise ValueError("work_date must be a date, not a datetime.")

        if total_work_minutes < 0:
            raise ValueError("total_work_minutes cannot be negative.")

        if total_break_minutes < 0:
            raise ValueError("total_break_minutes cannot be negative.")

        if isinstance(status, str):
            try:
                status = WorkdaySessionStatus(status.lower())
            except ValueError:
                raise ValueError(f"Invalid WorkdaySessionStatus: {status}")

        if status in (WorkdaySessionStatus.CLOSED, WorkdaySessionStatus.ABANDONED):
            if ended_at is None:
                raise ValueError(
                    f"Session in status '{status.value}' must have ended_at."
                )

        self.person_id = person_id
        self.person_name = person_name
        self.work_date = work_date
        self.status = status
        self.started_at = started_at
        self.ended_at = ended_at
        self.briefing_sent_at = briefing_sent_at
        self.total_work_minutes = total_work_minutes
        self.total_break_minutes = total_break_minutes
        self.timezone = timezone
        self.start_source_event_id = start_source_event_id
        self.end_source_event_id = end_source_event_id

    @classmethod
    def create(
        cls,
        *,
        person_id: str,
        person_name: str,
        started_at: datetime,
        timezone: str,
        work_date: date | None = None,
        status: WorkdaySessionStatus = WorkdaySessionStatus.ACTIVE,
        ended_at: datetime | None = None,
        briefing_sent_at: datetime | None = None,
        total_work_minutes: int = 0,
        total_break_minutes: int = 0,
        start_source_event_id: str | None = None,
        end_source_event_id: str | None = None,
        business_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkdaySession:
        """
        Create a new workday session aggregate.

        If work_date is omitted, it is derived from started_at in the
        provided timezone.
        """
        if not timezone or not timezone.strip():
            raise ValueError("timezone cannot be empty.")

        try:
            tz = ZoneInfo(timezone)
        except Exception as err:
            raise ValueError(f"Invalid timezone: {timezone}") from err

        if started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware (UTC).")

        if work_date is None:
            resolved_work_date = started_at.astimezone(tz).date()
        else:
            resolved_work_date = work_date

        return cls(
            identifier=Identifier(business_id=business_id),
            person_id=person_id,
            person_name=person_name,
            work_date=resolved_work_date,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            briefing_sent_at=briefing_sent_at,
            total_work_minutes=total_work_minutes,
            total_break_minutes=total_break_minutes,
            timezone=timezone,
            start_source_event_id=start_source_event_id,
            end_source_event_id=end_source_event_id,
            metadata=metadata,
        )

    def close(
        self,
        ended_at: datetime,
        *,
        end_source_event_id: str | None = None,
        total_work_minutes: int | None = None,
        total_break_minutes: int | None = None,
    ) -> None:
        """
        Close an active workday session.
        """
        if not self.is_active:
            raise ValueError(
                f"Cannot close session with status '{self.status.value}'. "
                "Only ACTIVE sessions can be closed."
            )

        if ended_at.tzinfo is None:
            raise ValueError("ended_at must be timezone-aware (UTC).")

        if ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at.")

        if total_work_minutes is not None and total_work_minutes < 0:
            raise ValueError("total_work_minutes cannot be negative.")

        if total_break_minutes is not None and total_break_minutes < 0:
            raise ValueError("total_break_minutes cannot be negative.")

        self.status = WorkdaySessionStatus.CLOSED
        self.ended_at = ended_at
        if end_source_event_id is not None:
            self.end_source_event_id = end_source_event_id
        if total_work_minutes is not None:
            self.total_work_minutes = total_work_minutes
        if total_break_minutes is not None:
            self.total_break_minutes = total_break_minutes
        self.touch()

    def abandon(
        self,
        *,
        reason: str | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        """
        Mark an active workday session as abandoned.
        """
        if not self.is_active:
            raise ValueError(
                f"Cannot abandon session with status '{self.status.value}'. "
                "Only ACTIVE sessions can be abandoned."
            )

        resolved_ended_at = ended_at or datetime.now(timezone.utc)
        if resolved_ended_at.tzinfo is None:
            raise ValueError("ended_at must be timezone-aware (UTC).")

        if resolved_ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at.")

        self.status = WorkdaySessionStatus.ABANDONED
        self.ended_at = resolved_ended_at
        if reason and reason.strip():
            self.metadata["abandon_reason"] = reason.strip()
        self.touch()

    def record_briefing_sent(
        self,
        sent_at: datetime | None = None,
    ) -> None:
        """
        Record the timestamp when the session briefing was delivered.
        """
        resolved_sent_at = sent_at or datetime.now(timezone.utc)
        if resolved_sent_at.tzinfo is None:
            raise ValueError("sent_at must be timezone-aware (UTC).")

        self.briefing_sent_at = resolved_sent_at
        self.touch()

    def update_durations(
        self,
        *,
        work_minutes: int,
        break_minutes: int,
    ) -> None:
        """
        Update cumulative work and break minutes.
        """
        if work_minutes < 0:
            raise ValueError("work_minutes cannot be negative.")

        if break_minutes < 0:
            raise ValueError("break_minutes cannot be negative.")

        self.total_work_minutes = work_minutes
        self.total_break_minutes = break_minutes
        self.touch()

    @property
    def is_active(self) -> bool:
        return self.status == WorkdaySessionStatus.ACTIVE

    @property
    def is_closed(self) -> bool:
        return self.status == WorkdaySessionStatus.CLOSED

    @property
    def is_abandoned(self) -> bool:
        return self.status == WorkdaySessionStatus.ABANDONED
