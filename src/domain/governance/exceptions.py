"""
Domain exceptions for governance, policy, and approvals.
"""

from __future__ import annotations


class GovernanceError(Exception):
    """Base exception for all governance errors."""


class InvalidApprovalTransitionError(GovernanceError):
    """Raised when an illegal approval state transition is attempted."""


class InvalidGovernanceTransitionError(GovernanceError):
    """Raised when an illegal governance finding/violation transition is attempted."""


class PolicyNotFoundError(GovernanceError):
    """Raised when a referenced policy does not exist."""


class ApprovalNotFoundError(GovernanceError):
    """Raised when a referenced approval request does not exist."""


class FindingNotFoundError(GovernanceError):
    """Raised when a referenced governance finding does not exist."""


class UnsupportedGovernanceEventError(GovernanceError):
    """Raised when an unsupported event type is provided for strict governance handling."""
