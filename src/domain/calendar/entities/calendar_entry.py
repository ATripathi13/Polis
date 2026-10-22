"""
Calendar entry domain entity for POLIS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from domain.common.identifier import Identifier
from domain.calendar.enums import (
    CalendarAudienceType,
    CalendarEntryStatus,
    CalendarEntryType,
)
from domain.calendar.exceptions import (
    InvalidCalendarEntryError,
    InvalidTimeRangeError,
)


@dataclass(slots=True)
class CalendarEntry:
    """Represents a scheduled activity, holiday, or announcement."""

    identifier: Identifier
    title: str
    description: str
    entry_type: CalendarEntryType
    creator_id: str
    start_time: datetime
    end_time: datetime | None
    timezone: str
    audience_type: CalendarAudienceType
    audience_id: str
    status: CalendarEntryStatus
    version: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @property
    def entry_id(self) -> str:
        return str(self.identifier.graph_id)

    def validate(self) -> None:
        """Validate state invariants."""
        if not self.title or not self.title.strip():
            raise InvalidCalendarEntryError("Calendar entry title cannot be empty.")

        if not self.creator_id or not self.creator_id.strip():
            raise InvalidCalendarEntryError("Calendar entry creator cannot be empty.")

        if self.start_time.tzinfo is None:
            raise InvalidTimeRangeError("Start time must be timezone-aware.")

        if self.end_time is not None:
            if self.end_time.tzinfo is None:
                raise InvalidTimeRangeError("End time must be timezone-aware.")
            if self.end_time < self.start_time:
                raise InvalidTimeRangeError("End time cannot precede start time.")

        if not self.timezone or not self.timezone.strip():
            raise InvalidTimeRangeError("Timezone cannot be empty.")

        try:
            ZoneInfo(self.timezone)
        except Exception as err:
            raise InvalidTimeRangeError(f"Invalid timezone: {self.timezone}") from err

        if not self.audience_id or not self.audience_id.strip():
            raise InvalidCalendarEntryError("Audience identifier cannot be empty.")

    def reschedule(
        self,
        new_start_time: datetime,
        new_end_time: datetime | None = None,
        new_timezone: str | None = None,
    ) -> None:
        """Reschedule entry to a new time and increment version."""
        if self.status == CalendarEntryStatus.CANCELLED:
            raise InvalidCalendarEntryError("Cannot reschedule a cancelled calendar entry.")

        if new_start_time.tzinfo is None:
            raise InvalidTimeRangeError("New start time must be timezone-aware.")

        if new_end_time is not None:
            if new_end_time.tzinfo is None:
                raise InvalidTimeRangeError("New end time must be timezone-aware.")
            if new_end_time < new_start_time:
                raise InvalidTimeRangeError("New end time cannot precede start time.")

        self.start_time = new_start_time
        self.end_time = new_end_time
        if new_timezone:
            ZoneInfo(new_timezone)  # Validate
            self.timezone = new_timezone
        self.version += 1
        self.updated_at = datetime.now(timezone.utc)
        self.validate()

    def cancel(self) -> None:
        """Cancel the calendar entry."""
        self.status = CalendarEntryStatus.CANCELLED
        self.updated_at = datetime.now(timezone.utc)

    def is_visible_to(
        self,
        user_id: str,
        user_team_ids: list[str] | tuple[str, ...] | None = None,
    ) -> bool:
        """Check whether entry is visible to the given user."""
        if not user_id:
            return False
        if self.creator_id == user_id:
            return True
        if self.audience_type == CalendarAudienceType.ORGANIZATION:
            return True
        if self.audience_type == CalendarAudienceType.INDIVIDUAL:
            return self.audience_id == user_id
        if self.audience_type == CalendarAudienceType.TEAM:
            return user_team_ids is not None and self.audience_id in user_team_ids
        return False

    @classmethod
    def create(
        cls,
        *,
        title: str,
        description: str = "",
        entry_type: CalendarEntryType,
        creator_id: str,
        start_time: datetime,
        end_time: datetime | None = None,
        timezone_name: str = "UTC",
        audience_type: CalendarAudienceType,
        audience_id: str,
        status: CalendarEntryStatus = CalendarEntryStatus.SCHEDULED,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        business_id: str = "",
    ) -> "CalendarEntry":
        now = datetime.now(timezone.utc)
        entry = cls(
            identifier=Identifier(business_id=business_id),
            title=title.strip(),
            description=description.strip(),
            entry_type=entry_type,
            creator_id=creator_id.strip(),
            start_time=start_time,
            end_time=end_time,
            timezone=timezone_name,
            audience_type=audience_type,
            audience_id=audience_id.strip(),
            status=status,
            version=version,
            metadata=dict(metadata or {}),
            created_at=created_at or now,
            updated_at=updated_at or now,
        )
        entry.validate()
        return entry
