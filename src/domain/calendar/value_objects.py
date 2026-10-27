"""
Calendar domain value objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import re

from domain.calendar.enums import CalendarAudienceType
from domain.calendar.exceptions import InvalidTimeRangeError


def is_raw_slack_id(val: str | None) -> bool:
    """Check whether a string matches a raw Slack user ID or mention pattern."""
    if not val:
        return False
    cleaned = val.strip()
    return bool(
        re.fullmatch(r"[UW][A-Z0-9_]{3,14}", cleaned)
        or re.fullmatch(r"<@[UW][A-Z0-9_]{3,14}(?:\|[^>]+)?>", cleaned)
        or re.fullmatch(r"user\s+[UW][A-Z0-9_]{3,14}", cleaned, re.IGNORECASE)
    )


_is_raw_slack_id = is_raw_slack_id


@dataclass(frozen=True, slots=True)
class CalendarAudience:
    """Represents a validated calendar audience."""

    audience_type: CalendarAudienceType
    audience_id: str
    display_name: str = ""
    resolved_recipients: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def individual(
        cls,
        user_id: str,
        display_name: str = "",
    ) -> "CalendarAudience":
        clean_name = display_name.strip() if display_name else ""
        if clean_name and (
            clean_name == user_id
            or _is_raw_slack_id(clean_name)
        ):
            clean_name = ""
        return cls(
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_id=user_id,
            display_name=clean_name,
            resolved_recipients=(user_id,),
        )

    @classmethod
    def team(
        cls,
        team_id: str,
        display_name: str = "",
        member_ids: tuple[str, ...] = (),
    ) -> "CalendarAudience":
        return cls(
            audience_type=CalendarAudienceType.TEAM,
            audience_id=team_id,
            display_name=display_name or team_id,
            resolved_recipients=member_ids,
        )

    @classmethod
    def organization(
        cls,
        organization_id: str = "organization",
        display_name: str = "Whole Organization",
        recipient_ids: tuple[str, ...] = (),
    ) -> "CalendarAudience":
        return cls(
            audience_type=CalendarAudienceType.ORGANIZATION,
            audience_id=organization_id,
            display_name=display_name,
            resolved_recipients=recipient_ids,
        )


@dataclass(frozen=True, slots=True)
class CalendarReminderPolicy:
    """Policy for calculating reminder due times."""

    offset_hours: int = 15

    def __post_init__(self) -> None:
        if self.offset_hours <= 0:
            raise ValueError("Reminder offset hours must be greater than zero.")

    def calculate_due_time(self, start_time: datetime) -> datetime:
        """Calculate the exact reminder due time from the scheduled start."""
        if start_time.tzinfo is None:
            raise InvalidTimeRangeError(
                "Scheduled start time must be timezone-aware."
            )
        return start_time - timedelta(hours=self.offset_hours)
