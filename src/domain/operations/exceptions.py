"""
Domain exceptions for POLIS operational intelligence.
"""

from __future__ import annotations


class OperationalError(Exception):
    """Base error for operational domain failures."""


class InvalidLifecycleTransitionError(OperationalError):
    """Raised when an invalid state transition is attempted on an operational item."""


class OperationalItemNotFoundError(OperationalError):
    """Raised when an operational item referenced by identifier cannot be found."""


class UnsupportedOperationalEventError(OperationalError):
    """Raised when an invalid or unhandled event is supplied to the operational layer."""
