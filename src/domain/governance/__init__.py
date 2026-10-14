"""
Governance domain package for POLIS.
"""

from .enums import (
    PolicyScope,
    PolicySeverity,
    PolicyEnforcementMode,
    PolicyEvaluationStatus,
    ComplianceStatus,
    ApprovalStatus,
    ViolationStatus,
)
from .exceptions import (
    GovernanceError,
    InvalidApprovalTransitionError,
    InvalidGovernanceTransitionError,
    PolicyNotFoundError,
    ApprovalNotFoundError,
    FindingNotFoundError,
    UnsupportedGovernanceEventError,
)
from .entities import (
    Policy,
    ApprovalRequest,
    GovernanceFinding,
)
from .value_objects import (
    GovernanceResult,
)
from .repositories import (
    GovernanceRepository,
    InMemoryGovernanceRepository,
)

__all__ = [
    # Enums
    "PolicyScope",
    "PolicySeverity",
    "PolicyEnforcementMode",
    "PolicyEvaluationStatus",
    "ComplianceStatus",
    "ApprovalStatus",
    "ViolationStatus",
    # Exceptions
    "GovernanceError",
    "InvalidApprovalTransitionError",
    "InvalidGovernanceTransitionError",
    "PolicyNotFoundError",
    "ApprovalNotFoundError",
    "FindingNotFoundError",
    "UnsupportedGovernanceEventError",
    # Entities & Value Objects
    "Policy",
    "ApprovalRequest",
    "GovernanceFinding",
    "GovernanceResult",
    # Repositories
    "GovernanceRepository",
    "InMemoryGovernanceRepository",
]
