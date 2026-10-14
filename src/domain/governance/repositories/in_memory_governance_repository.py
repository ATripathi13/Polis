"""
In-memory implementation of GovernanceRepository.
"""

from __future__ import annotations

from domain.governance.entities.policy import Policy
from domain.governance.entities.approval import ApprovalRequest
from domain.governance.entities.finding import GovernanceFinding
from domain.governance.enums import (
    PolicyScope,
    PolicySeverity,
    PolicyEnforcementMode,
    ApprovalStatus,
    ViolationStatus,
)
from domain.governance.repositories.governance_repository import GovernanceRepository


class InMemoryGovernanceRepository(GovernanceRepository):
    """
    Thread-safe in-memory governance repository for testing and runtime state.
    """

    def __init__(self, seed_default_policies: bool = True) -> None:
        self._policies: dict[str, Policy] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._findings: dict[str, GovernanceFinding] = {}

        if seed_default_policies:
            self._seed_default_policies()

    def _seed_default_policies(self) -> None:
        defaults = [
            Policy.create(
                policy_id="SEC-001",
                name="Production Access Control",
                description="Direct production database access requires explicit change authorization and multi-party approval.",
                scope=PolicyScope.SECURITY,
                severity=PolicySeverity.CRITICAL,
                enforcement_mode=PolicyEnforcementMode.BLOCKING,
                requires_approval=True,
                rule_description="Direct production database or SSH access without ticket authorization.",
                condition_keywords=["prod access", "production database", "direct prod", "ssh prod"],
            ),
            Policy.create(
                policy_id="DEP-001",
                name="Production Deployment Gate",
                description="Deployments to production environments must have verified tests and designated deployment approval.",
                scope=PolicyScope.DEPLOYMENT,
                severity=PolicySeverity.HIGH,
                enforcement_mode=PolicyEnforcementMode.MANDATORY,
                requires_approval=True,
                rule_description="Deploying code to production without QA sign-off or deployment authorization.",
                condition_keywords=["deploy prod", "production release", "deploy to production"],
            ),
            Policy.create(
                policy_id="DATA-001",
                name="Data Privacy & PII Protection",
                description="Customer personally identifiable information (PII) must not be transmitted in plain text or public channels.",
                scope=PolicyScope.DATA,
                severity=PolicySeverity.HIGH,
                enforcement_mode=PolicyEnforcementMode.BLOCKING,
                requires_approval=False,
                rule_description="Sharing unencrypted credentials, tokens, or customer PII in communication channels.",
                condition_keywords=["pii leak", "plaintext password", "api token leak", "customer secret"],
            ),
            Policy.create(
                policy_id="FIN-001",
                name="Budget & Expenditure Approval",
                description="Expenditures or cloud resource scale-ups exceeding budget limits require manager approval.",
                scope=PolicyScope.FINANCE,
                severity=PolicySeverity.MEDIUM,
                enforcement_mode=PolicyEnforcementMode.MANDATORY,
                requires_approval=True,
                rule_description="Unapproved expenditures or instance provisionings.",
                condition_keywords=["budget override", "unapproved expense", "unauthorized spend"],
            ),
        ]
        for p in defaults:
            self.save_policy(p)

    # -------------------------------------------------------------------------
    # Policies
    # -------------------------------------------------------------------------

    def find_policy(self, policy_id: str) -> Policy | None:
        return self._policies.get(policy_id)

    def list_policies(self, scope: PolicyScope | None = None) -> list[Policy]:
        if scope is None:
            return list(self._policies.values())
        return [p for p in self._policies.values() if p.scope == scope]

    def save_policy(self, policy: Policy) -> Policy:
        self._policies[policy.policy_id] = policy
        return policy

    # -------------------------------------------------------------------------
    # Approvals
    # -------------------------------------------------------------------------

    def find_approval(self, approval_id: str) -> ApprovalRequest | None:
        return self._approvals.get(approval_id)

    def find_approval_by_correlation(self, correlation_id: str) -> ApprovalRequest | None:
        if not correlation_id:
            return None
        for a in self._approvals.values():
            if a.correlation_id == correlation_id:
                return a
        return None

    def find_approval_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
    ) -> ApprovalRequest | None:
        if not source_event_id:
            return None
        for a in self._approvals.values():
            if a.source_event_id == source_event_id:
                if not source_type or a.source_type == source_type:
                    return a
        return None

    def save_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        self._approvals[approval.id] = approval
        return approval

    def list_pending_approvals(self) -> list[ApprovalRequest]:
        return [
            a for a in self._approvals.values()
            if a.status in (ApprovalStatus.REQUESTED, ApprovalStatus.PENDING)
        ]

    # -------------------------------------------------------------------------
    # Findings / Violations
    # -------------------------------------------------------------------------

    def find_finding(self, finding_id: str) -> GovernanceFinding | None:
        return self._findings.get(finding_id)

    def find_finding_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
    ) -> GovernanceFinding | None:
        if not source_event_id:
            return None
        for f in self._findings.values():
            if f.source_event_id == source_event_id:
                if not source_type or f.source_type == source_type:
                    return f
        return None

    def find_finding_by_correlation(self, correlation_id: str) -> list[GovernanceFinding]:
        if not correlation_id:
            return []
        return [f for f in self._findings.values() if f.correlation_id == correlation_id]

    def save_finding(self, finding: GovernanceFinding) -> GovernanceFinding:
        self._findings[finding.id] = finding
        return finding

    def list_findings(self, status: ViolationStatus | None = None) -> list[GovernanceFinding]:
        if status is None:
            return list(self._findings.values())
        return [f for f in self._findings.values() if f.status == status]
