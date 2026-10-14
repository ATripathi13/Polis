"""
GovernanceFinding entity representing policy evaluations, violations, and compliance state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from domain.governance.enums import (
    PolicySeverity,
    ViolationStatus,
    ComplianceStatus,
)


@dataclass(slots=True)
class GovernanceFinding:
    """
    Persistent record of a governance determination or policy violation.
    """
    id: str
    policy_id: str
    policy_name: str
    summary: str
    severity: PolicySeverity
    status: ViolationStatus
    compliance_status: ComplianceStatus
    affected_object: str
    evidence: list[str] = field(default_factory=list)
    source_event_id: str = ""
    source_type: str = ""
    correlation_id: str | None = None
    confidence: float = 1.0
    authority: str = "POLIS Governance Architecture"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    remediation_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    @classmethod
    def create(
        cls,
        policy_id: str,
        policy_name: str,
        summary: str,
        severity: PolicySeverity,
        *,
        id: str | None = None,
        status: ViolationStatus = ViolationStatus.OPEN,
        compliance_status: ComplianceStatus = ComplianceStatus.NON_COMPLIANT,
        affected_object: str = "",
        evidence: list[str] | None = None,
        source_event_id: str = "",
        source_type: str = "",
        correlation_id: str | None = None,
        confidence: float = 1.0,
        authority: str = "POLIS Governance Architecture",
        remediation_required: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> GovernanceFinding:
        now = datetime.now(timezone.utc)
        return cls(
            id=id or str(uuid.uuid4()),
            policy_id=policy_id.strip(),
            policy_name=policy_name.strip(),
            summary=summary.strip(),
            severity=severity,
            status=status,
            compliance_status=compliance_status,
            affected_object=affected_object.strip(),
            evidence=list(evidence or []),
            source_event_id=source_event_id.strip(),
            source_type=source_type.strip(),
            correlation_id=(
                str(getattr(correlation_id, "business_id", None) or getattr(correlation_id, "graph_id", None) or correlation_id).strip()
                if correlation_id is not None
                else None
            ),
            confidence=max(0.0, min(1.0, confidence)),
            authority=authority.strip(),
            created_at=now,
            updated_at=now,
            remediation_required=remediation_required,
            metadata=dict(metadata or {}),
        )
