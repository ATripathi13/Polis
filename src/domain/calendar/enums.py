"""
Calendar domain enums for POLIS.
"""

from __future__ import annotations

from enum import Enum


class CalendarEntryType(str, Enum):
    """Supported calendar entry types."""

    ACTIVITY = "activity"
    HOLIDAY = "holiday"
    ANNOUNCEMENT = "announcement"


class CalendarAudienceType(str, Enum):
    """Audience target scope."""

    INDIVIDUAL = "individual"
    TEAM = "team"
    ORGANIZATION = "organization"


class CalendarEntryStatus(str, Enum):
    """Lifecycle status of a calendar entry."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class CalendarDeliveryStatus(str, Enum):
    """Delivery status of a calendar reminder."""

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
