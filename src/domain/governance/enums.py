"""
Canonical governance and policy enums.
"""

from __future__ import annotations

from enum import Enum


class PolicyScope(str, Enum):
    """
    Scope of policy applicability.
    """
    ORGANIZATION = "organization"
    SECURITY = "security"
    DEPLOYMENT = "deployment"
    FINANCE = "finance"
    DATA = "data"
    COMMUNICATION = "communication"
    GENERAL = "general"


class PolicySeverity(str, Enum):
    """
    Severity level of a policy violation.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyEnforcementMode(str, Enum):
    """
    Enforcement mode for a policy.
    """
    MANDATORY = "mandatory"
    BLOCKING = "blocking"
    ADVISORY = "advisory"


class PolicyEvaluationStatus(str, Enum):
    """
    Evaluation outcomes for policy checks.
    """
    APPLIES = "applies"
    DOES_NOT_APPLY = "does_not_apply"
    COMPLIANT = "compliant"
    VIOLATION = "violation"
    UNCERTAIN = "uncertain"
    APPROVAL_REQUIRED = "approval_required"


class ComplianceStatus(str, Enum):
    """
    Compliance lifecycle state for organizational artifacts/events.
    """
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    UNDER_REVIEW = "under_review"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    EXEMPT = "exempt"
    UNKNOWN = "unknown"


class ApprovalStatus(str, Enum):
    """
    Lifecycle status for an approval request.
    """
    REQUESTED = "requested"
    PENDING = "pending"
    GRANTED = "granted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ViolationStatus(str, Enum):
    """
    Lifecycle status for a policy violation finding.
    """
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    REMEDIATION_REQUIRED = "remediation_required"
    REMEDIATED = "remediated"
    EXEMPT = "exempt"
    RESOLVED = "resolved"
    CLOSED = "closed"
