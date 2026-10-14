"""
GovernanceResult value object for structured machine-readable responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.governance.enums import (
    PolicyEvaluationStatus,
    ComplianceStatus,
)
from domain.governance.entities.finding import GovernanceFinding
from domain.governance.entities.approval import ApprovalRequest
from domain.organization.enums import OrganizationEventType


@dataclass(frozen=True, slots=True)
class GovernanceResult:
    """
    Standardized result emitted by the Governance Agent specialist.
    """
    operation: str
    compliance_status: ComplianceStatus = ComplianceStatus.UNKNOWN
    evaluation_status: PolicyEvaluationStatus = PolicyEvaluationStatus.DOES_NOT_APPLY
    event_type: OrganizationEventType | None = None
    policy_id: str | None = None
    policy_name: str | None = None
    finding: GovernanceFinding | None = None
    approval: ApprovalRequest | None = None
    idempotent: bool = False
    remediation_required: bool = False
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
