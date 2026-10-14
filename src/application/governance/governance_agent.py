"""
Governance Agent specialist capability for POLIS.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from domain.common.identifier import Identifier
from domain.governance.enums import (
    PolicyScope,
    PolicySeverity,
    PolicyEnforcementMode,
    PolicyEvaluationStatus,
    ComplianceStatus,
    ApprovalStatus,
    ViolationStatus,
)
from domain.governance.entities.policy import Policy
from domain.governance.entities.approval import ApprovalRequest
from domain.governance.entities.finding import GovernanceFinding
from domain.governance.value_objects.governance_result import GovernanceResult
from domain.governance.exceptions import (
    InvalidApprovalTransitionError,
    InvalidGovernanceTransitionError,
    PolicyNotFoundError,
    ApprovalNotFoundError,
    FindingNotFoundError,
    UnsupportedGovernanceEventError,
)
from domain.governance.repositories.governance_repository import GovernanceRepository
from domain.organization.enums import OrganizationEventType
from domain.organization.value_objects import OrganizationEvent
from domain.reasoning.value_objects import Question

logger = logging.getLogger(__name__)


class GovernanceAgent:
    """
    Production-grade Governance Specialist Agent for POLIS.

    Coordinates organizational policy evaluation, compliance lifecycle,
    authoritative approval workflows, violation finding provenance, and
    governance evidence retrieval.
    """

    _APPROVAL_TRANSITIONS: dict[ApprovalStatus, set[ApprovalStatus]] = {
        ApprovalStatus.REQUESTED: {
            ApprovalStatus.PENDING,
            ApprovalStatus.GRANTED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CANCELLED,
        },
        ApprovalStatus.PENDING: {
            ApprovalStatus.GRANTED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
        },
        ApprovalStatus.GRANTED: set(),  # Terminal
        ApprovalStatus.REJECTED: set(),  # Terminal
        ApprovalStatus.CANCELLED: set(),  # Terminal
        ApprovalStatus.EXPIRED: {
            ApprovalStatus.REQUESTED,  # Renewal
        },
    }

    _VIOLATION_TRANSITIONS: dict[ViolationStatus, set[ViolationStatus]] = {
        ViolationStatus.OPEN: {
            ViolationStatus.UNDER_REVIEW,
            ViolationStatus.REMEDIATION_REQUIRED,
            ViolationStatus.RESOLVED,
            ViolationStatus.CLOSED,
            ViolationStatus.EXEMPT,
        },
        ViolationStatus.UNDER_REVIEW: {
            ViolationStatus.REMEDIATION_REQUIRED,
            ViolationStatus.RESOLVED,
            ViolationStatus.CLOSED,
            ViolationStatus.EXEMPT,
        },
        ViolationStatus.REMEDIATION_REQUIRED: {
            ViolationStatus.REMEDIATED,
            ViolationStatus.CLOSED,
        },
        ViolationStatus.REMEDIATED: {
            ViolationStatus.CLOSED,
            ViolationStatus.OPEN,  # Re-emergence
        },
        ViolationStatus.RESOLVED: {
            ViolationStatus.CLOSED,
            ViolationStatus.OPEN,  # Re-opening
        },
        ViolationStatus.CLOSED: {
            ViolationStatus.OPEN,  # Re-opening
        },
        ViolationStatus.EXEMPT: {
            ViolationStatus.CLOSED,
            ViolationStatus.OPEN,
        },
    }

    def __init__(
        self,
        repository: GovernanceRepository,
        operations_agent: Any | None = None,
        knowledge_agent: Any | None = None,
        organization_event_repository: Any | None = None,
        enabled: bool = True,
    ) -> None:
        self._repository = repository
        self._operations_agent = operations_agent
        self._knowledge_agent = knowledge_agent
        self._organization_event_repository = organization_event_repository
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def repository(self) -> GovernanceRepository:
        return self._repository

    # =========================================================================
    # EVENT DISPATCH & LIFECYCLE MANAGEMENT
    # =========================================================================

    def process_event(
        self,
        event: OrganizationEvent,
        *,
        source_type: str = "",
        source_event_id: str = "",
        correlation_id: str | None = None,
        raise_on_unsupported: bool = False,
    ) -> GovernanceResult:
        """
        Process an organizational event and produce a structured GovernanceResult.
        """
        if not self._enabled:
            return GovernanceResult(
                operation="disabled",
                compliance_status=ComplianceStatus.UNKNOWN,
                evaluation_status=PolicyEvaluationStatus.DOES_NOT_APPLY,
                warnings=["Governance Agent is disabled by configuration."],
            )

        if not self._is_governance_event(event.event_type):
            if raise_on_unsupported:
                raise UnsupportedGovernanceEventError(
                    f"Event type '{event.event_type.value}' is not a governance event."
                )
            return GovernanceResult(
                event_type=event.event_type,
                operation="ignored",
                compliance_status=ComplianceStatus.UNKNOWN,
                evaluation_status=PolicyEvaluationStatus.DOES_NOT_APPLY,
                idempotent=True,
                warnings=[f"Event type '{event.event_type.value}' is not a governance event."],
            )

        # Canonical source and correlation resolution
        canonical_source_id = (
            str(getattr(source_event_id, "business_id", None) or getattr(source_event_id, "graph_id", None) or source_event_id).strip()
            if source_event_id is not None
            else ""
        )
        if not canonical_source_id:
            for obs in event.observations:
                for ev in obs.evidence:
                    if ev and str(ev).strip():
                        canonical_source_id = str(ev).strip()
                        break
                if canonical_source_id:
                    break

        canonical_source = (
            str(getattr(source_type, "business_id", None) or getattr(source_type, "graph_id", None) or source_type).strip()
            if source_type is not None
            else ""
        )
        if not canonical_source and event.observations:
            for obs in event.observations:
                meta = getattr(obs, "metadata", {}) or {}
                if "source_type" in meta:
                    canonical_source = str(meta["source_type"]).strip()
                    break

        correlation_id_str = (
            str(getattr(correlation_id, "business_id", None) or getattr(correlation_id, "graph_id", None) or correlation_id).strip()
            if correlation_id is not None
            else None
        )
        if not correlation_id_str and event.correlation_id is not None:
            if hasattr(event.correlation_id, "business_id") and event.correlation_id.business_id:
                correlation_id_str = str(event.correlation_id.business_id).strip()
            elif hasattr(event.correlation_id, "graph_id") and event.correlation_id.graph_id:
                correlation_id_str = str(event.correlation_id.graph_id).strip()
            else:
                s = str(event.correlation_id).strip()
                correlation_id_str = s if s else None

        if event.event_type == OrganizationEventType.POLICY_VIOLATION:
            return self._handle_policy_violation(
                event,
                source_type=canonical_source,
                source_event_id=canonical_source_id,
                correlation_id=correlation_id_str,
            )

        if event.event_type == OrganizationEventType.APPROVAL_GRANTED:
            return self._handle_approval_granted(
                event,
                source_type=canonical_source,
                source_event_id=canonical_source_id,
                correlation_id=correlation_id_str,
            )

        return GovernanceResult(
            event_type=event.event_type,
            operation="ignored",
            compliance_status=ComplianceStatus.UNKNOWN,
            evaluation_status=PolicyEvaluationStatus.DOES_NOT_APPLY,
            idempotent=True,
        )

    # =========================================================================
    # POLICY_VIOLATION HANDLING
    # =========================================================================

    def _handle_policy_violation(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | None,
    ) -> GovernanceResult:
        # Idempotency check: look for existing finding by source_event or correlation
        existing = None
        if source_event_id:
            existing = self._repository.find_finding_by_source_event(source_type, source_event_id)
        if existing is None and correlation_id:
            corr_findings = self._repository.find_finding_by_correlation(correlation_id)
            if corr_findings:
                existing = corr_findings[0]

        if existing is not None:
            if existing.summary.strip().lower() == event.summary.strip().lower():
                return GovernanceResult(
                    event_type=event.event_type,
                    operation="no_op",
                    compliance_status=existing.compliance_status,
                    evaluation_status=PolicyEvaluationStatus.VIOLATION,
                    policy_id=existing.policy_id,
                    policy_name=existing.policy_name,
                    finding=existing,
                    idempotent=True,
                    evidence=list(existing.evidence),
                    correlation_id=correlation_id,
                    remediation_required=existing.remediation_required,
                )

        # Policy identification
        policy = self._identify_policy_for_event(event)

        meta = self._merge_event_metadata(event)
        severity = self._extract_severity(event, fallback=policy.severity if policy else PolicySeverity.MEDIUM)
        affected_object = str(meta.get("affected_object") or meta.get("target") or meta.get("resource") or "general").strip()

        evidence = [
            ev
            for obs in event.observations
            for ev in obs.evidence
            if ev
        ]
        if source_event_id and source_event_id not in evidence:
            evidence.append(source_event_id)

        remediation_required = bool(
            meta.get("remediation_required")
            or severity in (PolicySeverity.HIGH, PolicySeverity.CRITICAL)
        )

        finding = GovernanceFinding.create(
            policy_id=policy.policy_id if policy else "POL-GENERAL",
            policy_name=policy.name if policy else "General Organizational Policy",
            summary=event.summary,
            severity=severity,
            status=ViolationStatus.REMEDIATION_REQUIRED if remediation_required else ViolationStatus.OPEN,
            compliance_status=ComplianceStatus.NON_COMPLIANT,
            affected_object=affected_object,
            evidence=evidence,
            source_event_id=source_event_id,
            source_type=source_type,
            correlation_id=correlation_id,
            confidence=event.confidence,
            authority=policy.authority if policy else "POLIS Governance Architecture",
            remediation_required=remediation_required,
            metadata=meta,
        )

        saved = self._repository.save_finding(finding)

        # Coordinate remediation with OperationsAgent if configured and required
        if remediation_required and self._operations_agent is not None:
            self._trigger_operational_remediation(saved, event, correlation_id)

        return GovernanceResult(
            event_type=event.event_type,
            operation="violation_registered",
            compliance_status=ComplianceStatus.NON_COMPLIANT,
            evaluation_status=PolicyEvaluationStatus.VIOLATION,
            policy_id=saved.policy_id,
            policy_name=saved.policy_name,
            finding=saved,
            idempotent=False,
            remediation_required=remediation_required,
            evidence=saved.evidence,
            correlation_id=correlation_id,
        )

    # =========================================================================
    # APPROVAL_GRANTED HANDLING
    # =========================================================================

    def _handle_approval_granted(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | None,
    ) -> GovernanceResult:
        meta = self._merge_event_metadata(event)
        approver_id = str(meta.get("approver_id") or meta.get("approver") or meta.get("user_id") or "authorizer").strip()
        approval_id_hint = str(meta.get("approval_id") or meta.get("request_id") or "").strip()
        target_object = str(meta.get("target_object") or meta.get("target") or event.summary).strip()

        # Idempotency / resolution check
        existing = None
        if approval_id_hint:
            existing = self._repository.find_approval(approval_id_hint)
        if existing is None and source_event_id:
            existing = self._repository.find_approval_by_source_event(source_type, source_event_id)
        if existing is None and correlation_id:
            existing = self._repository.find_approval_by_correlation(correlation_id)

        if existing is not None:
            if existing.status == ApprovalStatus.GRANTED:
                return GovernanceResult(
                    event_type=event.event_type,
                    operation="no_op",
                    compliance_status=ComplianceStatus.APPROVED,
                    evaluation_status=PolicyEvaluationStatus.COMPLIANT,
                    approval=existing,
                    idempotent=True,
                    evidence=list(existing.evidence),
                    correlation_id=correlation_id,
                )

            # Validate transition
            self.validate_approval_transition(existing.status, ApprovalStatus.GRANTED)

            existing.status = ApprovalStatus.GRANTED
            existing.approver_id = approver_id
            existing.granted_at = datetime.now(timezone.utc)
            if source_event_id and source_event_id not in existing.evidence:
                existing.evidence = list(existing.evidence) + [source_event_id]

            saved = self._repository.save_approval(existing)
            return GovernanceResult(
                event_type=event.event_type,
                operation="approval_granted",
                compliance_status=ComplianceStatus.APPROVED,
                evaluation_status=PolicyEvaluationStatus.COMPLIANT,
                approval=saved,
                idempotent=False,
                evidence=saved.evidence,
                correlation_id=correlation_id,
            )

        # If no prior approval record existed, create directly in GRANTED state
        evidence = [
            ev
            for obs in event.observations
            for ev in obs.evidence
            if ev
        ]
        if source_event_id and source_event_id not in evidence:
            evidence.append(source_event_id)

        approval = ApprovalRequest.create(
            title=event.summary,
            target_object=target_object,
            requester_id=str(meta.get("requester_id") or "system").strip(),
            status=ApprovalStatus.GRANTED,
            source_event_id=source_event_id,
            source_type=source_type,
            correlation_id=correlation_id,
            evidence=evidence,
            notes=str(meta.get("notes", "")),
            metadata=meta,
        )
        approval.approver_id = approver_id
        approval.granted_at = datetime.now(timezone.utc)

        saved = self._repository.save_approval(approval)
        return GovernanceResult(
            event_type=event.event_type,
            operation="approval_granted",
            compliance_status=ComplianceStatus.APPROVED,
            evaluation_status=PolicyEvaluationStatus.COMPLIANT,
            approval=saved,
            idempotent=False,
            evidence=saved.evidence,
            correlation_id=correlation_id,
        )

    # =========================================================================
    # POLICY EVALUATION
    # =========================================================================

    def evaluate(
        self,
        subject: str,
        context: dict[str, Any] | None = None,
        policy_id: str | None = None,
    ) -> GovernanceResult:
        """
        Evaluate a subject string or context dictionary against active policies.
        """
        ctx = dict(context or {})
        subject_clean = subject.strip()

        # If specific policy requested
        if policy_id:
            policy = self._repository.find_policy(policy_id)
            if policy is None:
                raise PolicyNotFoundError(f"Policy '{policy_id}' not found.")
            return self._evaluate_single_policy(policy, subject_clean, ctx)

        # Check against all policies
        policies = self._repository.list_policies()
        matched_policies = [p for p in policies if self._policy_applies(p, subject_clean, ctx)]

        if not matched_policies:
            return GovernanceResult(
                operation="evaluated",
                compliance_status=ComplianceStatus.UNKNOWN,
                evaluation_status=PolicyEvaluationStatus.DOES_NOT_APPLY,
                evidence=[f"No matching policies apply to subject: '{subject_clean}'"],
            )

        # Evaluate the most restrictive matched policy.
        enforcement_priority = {
            PolicyEnforcementMode.BLOCKING: 0,
            PolicyEnforcementMode.MANDATORY: 1,
            PolicyEnforcementMode.ADVISORY: 2,
        }
        severity_priority = {
            PolicySeverity.CRITICAL: 0,
            PolicySeverity.HIGH: 1,
            PolicySeverity.MEDIUM: 2,
            PolicySeverity.LOW: 3,
        }
        primary_policy = min(
            matched_policies,
            key=lambda policy: (
                enforcement_priority[policy.enforcement_mode],
                severity_priority[policy.severity],
                policy.policy_id,
            ),
        )
        return self._evaluate_single_policy(primary_policy, subject_clean, ctx)

    def _evaluate_single_policy(
        self,
        policy: Policy,
        subject: str,
        context: dict[str, Any],
    ) -> GovernanceResult:
        applies = self._policy_applies(policy, subject, context)
        if not applies:
            return GovernanceResult(
                operation="evaluated",
                compliance_status=ComplianceStatus.UNKNOWN,
                evaluation_status=PolicyEvaluationStatus.DOES_NOT_APPLY,
                policy_id=policy.policy_id,
                policy_name=policy.name,
            )

        # 1. Check explicit violation indicators in context
        has_violation = bool(
            context.get("is_violation")
            or context.get("violation_detected")
            or context.get("unauthorized")
        )
        if has_violation:
            return GovernanceResult(
                operation="evaluated",
                compliance_status=ComplianceStatus.NON_COMPLIANT,
                evaluation_status=PolicyEvaluationStatus.VIOLATION,
                policy_id=policy.policy_id,
                policy_name=policy.name,
                evidence=[f"Explicit violation of {policy.policy_id}: {policy.rule_description}"],
            )

        # 2. Check if verified compliant
        if context.get("compliant") is True and (not policy.requires_approval or context.get("approved") is True):
            return GovernanceResult(
                operation="evaluated",
                compliance_status=ComplianceStatus.COMPLIANT,
                evaluation_status=PolicyEvaluationStatus.COMPLIANT,
                policy_id=policy.policy_id,
                policy_name=policy.name,
                evidence=[f"Compliance verified for policy {policy.policy_id}."],
            )

        # 3. Check approval requirement
        if policy.requires_approval:
            has_approval = bool(
                context.get("approved")
                or context.get("approval_granted")
                or context.get("has_approval")
            )
            if not has_approval:
                return GovernanceResult(
                    operation="evaluated",
                    compliance_status=ComplianceStatus.APPROVAL_REQUIRED,
                    evaluation_status=PolicyEvaluationStatus.APPROVAL_REQUIRED,
                    policy_id=policy.policy_id,
                    policy_name=policy.name,
                    evidence=[f"Policy {policy.policy_id} ({policy.name}) requires explicit authorization."],
                )
            # If approved and no violation, it's compliant
            return GovernanceResult(
                operation="evaluated",
                compliance_status=ComplianceStatus.COMPLIANT,
                evaluation_status=PolicyEvaluationStatus.COMPLIANT,
                policy_id=policy.policy_id,
                policy_name=policy.name,
                evidence=[f"Compliance verified with approval for policy {policy.policy_id}."],
            )

        # If evidence is incomplete or ambiguous, explicitly return UNCERTAIN
        return GovernanceResult(
            operation="evaluated",
            compliance_status=ComplianceStatus.UNDER_REVIEW,
            evaluation_status=PolicyEvaluationStatus.UNCERTAIN,
            policy_id=policy.policy_id,
            policy_name=policy.name,
            warnings=["Evidence is insufficient to confirm compliance or rule violation."],
            evidence=[f"Policy applies: {policy.name}. Further verification required."],
        )

    def _policy_applies(self, policy: Policy, subject: str, context: dict[str, Any]) -> bool:
        lowered = subject.lower()
        if policy.scope.value in lowered:
            return True
        for kw in policy.condition_keywords:
            if kw.lower() in lowered:
                return True
        scope_in_ctx = str(context.get("scope", "")).lower()
        if scope_in_ctx and scope_in_ctx == policy.scope.value:
            return True
        return False

    # =========================================================================
    # APPROVAL WORKFLOW
    # =========================================================================

    def request_approval(
        self,
        title: str,
        target_object: str,
        requester_id: str,
        *,
        policy_id: str | None = None,
        correlation_id: str | None = None,
        notes: str = "",
    ) -> ApprovalRequest:
        """
        Create a new explicit approval request.
        """
        approval = ApprovalRequest.create(
            title=title,
            target_object=target_object,
            requester_id=requester_id,
            status=ApprovalStatus.REQUESTED,
            policy_id=policy_id,
            correlation_id=correlation_id,
            notes=notes,
        )
        return self._repository.save_approval(approval)

    def grant_approval(
        self,
        approval_id: str,
        approver_id: str,
        notes: str = "",
    ) -> ApprovalRequest:
        """
        Transition an approval request to GRANTED.
        """
        approval = self._repository.find_approval(approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval request '{approval_id}' not found.")

        self.validate_approval_transition(approval.status, ApprovalStatus.GRANTED)
        approval.status = ApprovalStatus.GRANTED
        approval.approver_id = approver_id.strip()
        approval.granted_at = datetime.now(timezone.utc)
        if notes:
            approval.notes = f"{approval.notes}\n{notes}".strip()

        return self._repository.save_approval(approval)

    def reject_approval(
        self,
        approval_id: str,
        approver_id: str,
        reason: str = "",
    ) -> ApprovalRequest:
        """
        Transition an approval request to REJECTED.
        """
        approval = self._repository.find_approval(approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval request '{approval_id}' not found.")

        self.validate_approval_transition(approval.status, ApprovalStatus.REJECTED)
        approval.status = ApprovalStatus.REJECTED
        approval.approver_id = approver_id.strip()
        if reason:
            approval.notes = f"{approval.notes}\nRejection reason: {reason}".strip()

        return self._repository.save_approval(approval)

    # =========================================================================
    # LIFECYCLE TRANSITION VALIDATORS
    # =========================================================================

    def validate_approval_transition(
        self,
        current_status: ApprovalStatus,
        target_status: ApprovalStatus,
    ) -> None:
        if current_status == target_status:
            return
        allowed = self._APPROVAL_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise InvalidApprovalTransitionError(
                f"Cannot transition approval from '{current_status.value}' to '{target_status.value}'. "
                f"Allowed transitions: {[s.value for s in allowed]}."
            )

    def validate_governance_transition(
        self,
        current_status: ViolationStatus,
        target_status: ViolationStatus,
    ) -> None:
        if current_status == target_status:
            return
        allowed = self._VIOLATION_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise InvalidGovernanceTransitionError(
                f"Cannot transition governance finding from '{current_status.value}' to '{target_status.value}'. "
                f"Allowed transitions: {[s.value for s in allowed]}."
            )

    # =========================================================================
    # QUERIES, EVIDENCE & REASONING
    # =========================================================================

    def get_policy(self, policy_id: str) -> Policy | None:
        return self._repository.find_policy(policy_id)

    def list_policies(self, scope: PolicyScope | None = None) -> list[Policy]:
        return self._repository.list_policies(scope=scope)

    def get_violations(self, status: ViolationStatus | None = None) -> list[GovernanceFinding]:
        return self._repository.list_findings(status=status)

    def get_pending_approvals(self) -> list[ApprovalRequest]:
        return self._repository.list_pending_approvals()

    def get_governance_state(self) -> dict[str, Any]:
        """
        High-level summary of active governance posture.
        """
        policies = self.list_policies()
        violations = self.get_violations()
        open_violations = [v for v in violations if v.status in (ViolationStatus.OPEN, ViolationStatus.REMEDIATION_REQUIRED)]
        pending_approvals = self.get_pending_approvals()

        return {
            "policy_count": len(policies),
            "total_findings": len(violations),
            "open_violations_count": len(open_violations),
            "pending_approvals_count": len(pending_approvals),
            "open_violations": [
                {
                    "id": v.id,
                    "policy_id": v.policy_id,
                    "summary": v.summary,
                    "severity": v.severity.value,
                    "status": v.status.value,
                }
                for v in open_violations
            ],
            "pending_approvals": [
                {
                    "id": a.id,
                    "title": a.title,
                    "target_object": a.target_object,
                    "requester_id": a.requester_id,
                    "status": a.status.value,
                }
                for a in pending_approvals
            ],
        }

    def retrieve_evidence(self, question: Question | str) -> list[str]:
        """
        Retrieve formatted governance evidence for POLIS question answering.
        """
        q_text = (question.text if isinstance(question, Question) else str(question)).lower().strip()
        evidence_lines: list[str] = []

        # 1. Matching violations
        violations = self.get_violations()
        for v in violations:
            if any(term in q_text for term in (v.policy_id.lower(), v.summary.lower(), "violation", "compliance", "policy", "audit")):
                evidence_lines.append(
                    f"Governance Finding [{v.policy_id}] ({v.severity.value.upper()}): {v.summary} "
                    f"[Status: {v.status.value}, Affected: {v.affected_object}]"
                )

        # 2. Matching pending approvals
        approvals = self.get_pending_approvals()
        for a in approvals:
            if any(term in q_text for term in ("approval", "pending", a.target_object.lower(), a.title.lower())):
                evidence_lines.append(
                    f"Pending Approval: '{a.title}' for '{a.target_object}' requested by {a.requester_id} [Status: {a.status.value}]"
                )

        # 3. Matching policies
        for p in self.list_policies():
            if any(term in q_text for term in (p.policy_id.lower(), p.name.lower(), p.scope.value)):
                evidence_lines.append(
                    f"Policy [{p.policy_id}] {p.name}: {p.description} (Authority: {p.authority})"
                )

        return evidence_lines

    def ask(self, question: Question | str) -> dict[str, Any]:
        """
        Query governance intelligence for a specific question.
        """
        q_text = question.text if isinstance(question, Question) else str(question)
        evidence = self.retrieve_evidence(question)
        return {
            "question": q_text,
            "evidence": evidence,
            "governance_state": self.get_governance_state(),
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _identify_policy_for_event(self, event: OrganizationEvent) -> Policy | None:
        meta = self._merge_event_metadata(event)
        policy_id = str(meta.get("policy_id") or "").strip()
        if policy_id:
            found = self._repository.find_policy(policy_id)
            if found is not None:
                return found

        policy_name = str(meta.get("policy_name") or "").strip().lower()
        for p in self._repository.list_policies():
            if policy_name and p.name.lower() == policy_name:
                return p
            for kw in p.condition_keywords:
                if kw.lower() in event.summary.lower():
                    return p
        return None

    def _trigger_operational_remediation(
        self,
        finding: GovernanceFinding,
        event: OrganizationEvent,
        correlation_id: str | None,
    ) -> None:
        try:
            # Create a remediation risk via OperationsAgent
            from domain.observation import Observation, ObservationType
            from domain.organization import OrganizationEvent, OrganizationEventType

            risk_summary = f"Governance Remediation: {finding.policy_name} - {finding.summary}"
            obs = Observation(
                observation_type=ObservationType.RISK,
                summary=risk_summary,
                evidence=finding.evidence,
                confidence=finding.confidence,
                metadata={
                    "severity": finding.severity.value,
                    "policy_id": finding.policy_id,
                    "finding_id": finding.id,
                    "remediation": True,
                },
            )
            remediation_event = OrganizationEvent(
                event_type=OrganizationEventType.RISK_IDENTIFIED,
                summary=risk_summary,
                observations=[obs],
                confidence=finding.confidence,
            )
            self._operations_agent.process_event(
                remediation_event,
                source_type="governance",
                source_event_id=finding.source_event_id or finding.id,
                correlation_id=correlation_id,
            )
        except Exception as e:
            logger.warning("Failed to trigger operational remediation for finding %s: %s", finding.id, e)

    @staticmethod
    def _is_governance_event(event_type: OrganizationEventType) -> bool:
        return event_type in (
            OrganizationEventType.POLICY_VIOLATION,
            OrganizationEventType.APPROVAL_GRANTED,
        )

    @staticmethod
    def _extract_severity(event: OrganizationEvent, fallback: PolicySeverity) -> PolicySeverity:
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            raw = str(meta.get("severity", "") or meta.get("priority", "")).lower().strip()
            if raw == "critical":
                return PolicySeverity.CRITICAL
            if raw == "high":
                return PolicySeverity.HIGH
            if raw == "medium":
                return PolicySeverity.MEDIUM
            if raw == "low":
                return PolicySeverity.LOW
        return fallback

    @staticmethod
    def _merge_event_metadata(event: OrganizationEvent) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            result.update(meta)
        return result
