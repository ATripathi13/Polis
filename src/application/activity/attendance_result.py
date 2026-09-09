from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class BreakPeriod:
    """
    A break observed during a work session.
    """

    started_at: datetime
    ended_at: datetime | None = None

    def duration(
        self,
        *,
        now: datetime,
    ) -> timedelta:
        """
        Return the break duration.

        If the break is still active, calculate up to `now`.
        """
        end = self.ended_at or now

        if end <= self.started_at:
            return timedelta(0)

        return end - self.started_at

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


@dataclass(frozen=True, slots=True)
class AttendanceResult:
    """
    Deterministic attendance calculation for one person.
    """

    person_id: str
    person_name: str

    work_started_at: datetime | None = None
    work_ended_at: datetime | None = None

    breaks: list[BreakPeriod] = field(
        default_factory=list,
    )

    total_break_duration: timedelta = timedelta(0)
    active_work_duration: timedelta = timedelta(0)

    current_state: str = "unknown"

    @property
    def current_break(self) -> BreakPeriod | None:
        for break_period in reversed(self.breaks):
            if break_period.is_active:
                return break_period

        return None
