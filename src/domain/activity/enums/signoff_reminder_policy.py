from __future__ import annotations

from enum import Enum


class SignoffReminderPolicy(str, Enum):
    """Policy governing reminder delivery after a person signs off for the day."""

    CONTINUE = "continue"
    PAUSE_UNTIL_NEXT_WORKDAY = "pause_until_next_workday"
