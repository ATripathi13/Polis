from __future__ import annotations

from enum import Enum


class WorkdaySessionStatus(str, Enum):
    """Lifecycle status of a workday session."""

    ACTIVE = "active"
    CLOSED = "closed"
    ABANDONED = "abandoned"
