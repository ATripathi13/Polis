"""
Calendar domain exceptions.
"""

from __future__ import annotations


class CalendarDomainError(Exception):
    """Base exception for all calendar domain errors."""


class CalendarEntryNotFoundError(CalendarDomainError):
    """Raised when a calendar entry is not found."""


class InvalidCalendarEntryError(CalendarDomainError):
    """Raised when calendar entry fields are invalid."""


class InvalidAudienceError(CalendarDomainError):
    """Raised when audience specification is invalid or unresolvable."""


class InvalidTimeRangeError(CalendarDomainError):
    """Raised when time range or timezone is invalid."""


class UnauthorizedCalendarActionError(CalendarDomainError):
    """Raised when user is not authorized to modify or view a calendar entry."""
