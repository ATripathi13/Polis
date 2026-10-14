"""
Unit tests for the Governance Agent specialist.
"""

from datetime import datetime, timezone
import pytest

from domain.governance import (
    Policy,
    PolicyScope,
    PolicySeverity,
    PolicyEnforcementMode,
    PolicyEvaluationStatus,
    ComplianceStatus,
    ApprovalStatus,
    ViolationStatus,
    ApprovalRequest,
    GovernanceFinding,
    InMemoryGovernanceRepository,
    InvalidApprovalTransitionError,
    InvalidGovernanceTransitionError,
    PolicyNotFoundError,
    ApprovalNotFoundError,
    UnsupportedGovernanceEventError,
)
from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from domain.observation import (
    Observation,
    ObservationType,
)
from domain.reasoning.value_objects import Question
from application.governance import GovernanceAgent


def _make_event(
    event_type: OrganizationEventType,
    summary: str,
    *,
    metadata: dict | None = None,
    evidence: list[str] | None = None,
    confidence: float = 0.95,
) -> OrganizationEvent:
    meta = metadata or {}
    obs_type = (
        ObservationType.ALERT
        if event_type == OrganizationEventType.POLICY_VIOLATION
        else (
            ObservationType.APPROVAL
            if event_type == OrganizationEventType.APPROVAL_GRANTED
            else ObservationType.TASK
        )
    )
    obs = Observation(
        observation_type=obs_type,
        summary=summary,
        evidence=evidence or ["slack ref 999"],
        confidence=confidence,
        metadata=meta,
    )
    return OrganizationEvent(
        event_type=event_type,
        summary=summary,
        observations=[obs],
        confidence=confidence,
    )


class FakeOperationsAgent:
    def __init__(self):
        self.processed_events = []

    def process_event(self, event, **kwargs):
        self.processed_events.append((event, kwargs))
        return event


@pytest.fixture
def repo():
    return InMemoryGovernanceRepository(seed_default_policies=True)


@pytest.fixture
def ops_agent():
    return FakeOperationsAgent()


@pytest.fixture
def agent(repo, ops_agent):
    return GovernanceAgent(
        repository=repo,
        operations_agent=ops_agent,
        enabled=True,
    )


# -----------------------------------------------------------------------------
# A: Governance Agent Initialization
# -----------------------------------------------------------------------------

def test_governance_agent_initialization(agent, repo):
    assert agent.enabled is True
    assert agent.repository is repo
    policies = agent.list_policies()
    assert len(policies) >= 4  # Default seeded policies


# -----------------------------------------------------------------------------
# B & C: POLICY_VIOLATION Processing & Replay Idempotency
# -----------------------------------------------------------------------------

def test_policy_violation_processing(agent, repo):
    evt = _make_event(
        OrganizationEventType.POLICY_VIOLATION,
        "Engineer connected directly to production database without ticket",
        metadata={
            "policy_id": "SEC-001",
            "severity": "critical",
            "affected_object": "prod-db-replica-1",
            "remediation_required": True,
        },
        evidence=["audit-log-ref-1"],
    )

    result = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="evt-sec-1",
        correlation_id="corr-sec-1",
    )

    assert result.operation == "violation_registered"
    assert result.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert result.evaluation_status == PolicyEvaluationStatus.VIOLATION
    assert result.idempotent is False
    assert result.policy_id == "SEC-001"
    assert result.finding is not None
    assert result.finding.severity == PolicySeverity.CRITICAL
    assert result.remediation_required is True
    assert "audit-log-ref-1" in result.evidence

    # Check repository state
    findings = repo.list_findings()
    assert len(findings) == 1
    assert findings[0].policy_id == "SEC-001"


def test_policy_violation_replay_idempotency(agent, repo):
    evt = _make_event(
        OrganizationEventType.POLICY_VIOLATION,
        "Engineer connected directly to production database without ticket",
        metadata={"policy_id": "SEC-001"},
    )

    res1 = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="evt-sec-replay",
        correlation_id="corr-sec-replay",
    )
    assert res1.operation == "violation_registered"
    assert res1.idempotent is False

    # Second processing
    res2 = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="evt-sec-replay",
        correlation_id="corr-sec-replay",
    )
    assert res2.operation == "no_op"
    assert res2.idempotent is True
    assert len(repo.list_findings()) == 1


# -----------------------------------------------------------------------------
# D & E: Policy Identification & Applicability
# -----------------------------------------------------------------------------

def test_policy_identification_via_keywords(agent, repo):
    evt = _make_event(
        OrganizationEventType.POLICY_VIOLATION,
        "Unapproved deploy prod attempted by intern",
        metadata={},
    )
    res = agent.process_event(
        evt,
        source_type="github",
        source_event_id="gh-123",
    )
    # Matches DEP-001 keywords ("deploy prod")
    assert res.policy_id == "DEP-001"
    assert res.policy_name == "Production Deployment Gate"


def test_policy_applicability_evaluation(agent):
    # Applies
    res_applies = agent.evaluate("deploy prod to us-east-1", {"scope": "deployment"})
    assert res_applies.evaluation_status != PolicyEvaluationStatus.DOES_NOT_APPLY

    # Does not apply
    res_na = agent.evaluate("Casual lunch at 12pm", {})
    assert res_na.evaluation_status == PolicyEvaluationStatus.DOES_NOT_APPLY
    assert res_na.compliance_status == ComplianceStatus.UNKNOWN


# -----------------------------------------------------------------------------
# F, G, H, I: Policy Evaluation Outcomes (Compliant, Violation, Uncertain, Approval Required)
# -----------------------------------------------------------------------------

def test_evaluation_compliant_result(agent):
    res = agent.evaluate(
        "Deploy to production",
        {"approved": True, "compliant": True, "scope": "deployment"},
        policy_id="DEP-001",
    )
    assert res.evaluation_status == PolicyEvaluationStatus.COMPLIANT
    assert res.compliance_status == ComplianceStatus.COMPLIANT


def test_evaluation_violation_result(agent):
    res = agent.evaluate(
        "Deploy to production without checks",
        {"is_violation": True, "scope": "deployment"},
        policy_id="DEP-001",
    )
    assert res.evaluation_status == PolicyEvaluationStatus.VIOLATION
    assert res.compliance_status == ComplianceStatus.NON_COMPLIANT


def test_evaluation_approval_required_result(agent):
    res = agent.evaluate(
        "Direct production database scale up",
        {"has_approval": False},
        policy_id="SEC-001",
    )
    assert res.evaluation_status == PolicyEvaluationStatus.APPROVAL_REQUIRED
    assert res.compliance_status == ComplianceStatus.APPROVAL_REQUIRED


def test_evaluation_uncertain_result(agent):
    # Policy applies (DATA-001 has requires_approval=False) but evidence is ambiguous/incomplete
    res = agent.evaluate(
        "Analyzing customer data pipeline throughput",
        {"scope": "data"},
        policy_id="DATA-001",
    )
    assert res.evaluation_status == PolicyEvaluationStatus.UNCERTAIN
    assert res.compliance_status == ComplianceStatus.UNDER_REVIEW


# -----------------------------------------------------------------------------
# J & K: APPROVAL_GRANTED Processing & Replay Idempotency
# -----------------------------------------------------------------------------

def test_approval_granted_processing(agent, repo):
    # Pre-create an approval request
    req = agent.request_approval(
        title="Promote release candidate v2.4 to prod",
        target_object="deployment:release-v2.4",
        requester_id="alice",
        policy_id="DEP-001",
        correlation_id="corr-rel-24",
    )
    assert req.status == ApprovalStatus.REQUESTED

    # Event arrives granting approval
    evt = _make_event(
        OrganizationEventType.APPROVAL_GRANTED,
        "Production release v2.4 approved by VP of Eng",
        metadata={
            "approval_id": req.id,
            "approver_id": "bob-vp",
        },
    )

    res = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="appr-evt-1",
        correlation_id="corr-rel-24",
    )

    assert res.operation == "approval_granted"
    assert res.compliance_status == ComplianceStatus.APPROVED
    assert res.approval is not None
    assert res.approval.status == ApprovalStatus.GRANTED
    assert res.approval.approver_id == "bob-vp"


def test_approval_granted_replay_idempotency(agent, repo):
    evt = _make_event(
        OrganizationEventType.APPROVAL_GRANTED,
        "Emergency firewall change approved",
        metadata={"approver_id": "sec-lead"},
    )

    res1 = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="appr-rep-1",
        correlation_id="corr-fw-1",
    )
    assert res1.operation == "approval_granted"
    assert res1.idempotent is False

    res2 = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="appr-rep-1",
        correlation_id="corr-fw-1",
    )
    assert res2.operation == "no_op"
    assert res2.idempotent is True
    assert len(agent.get_pending_approvals()) == 0


# -----------------------------------------------------------------------------
# L, M, N: Approval and Governance Lifecycles & Invalid Transition Rejections
# -----------------------------------------------------------------------------

def test_approval_lifecycle_workflow(agent):
    req = agent.request_approval(
        title="Budget scale up",
        target_object="aws:rds-cluster",
        requester_id="carol",
    )
    assert req.status == ApprovalStatus.REQUESTED

    # Grant
    granted = agent.grant_approval(req.id, "finance-director", notes="Budget approved")
    assert granted.status == ApprovalStatus.GRANTED
    assert granted.approver_id == "finance-director"


def test_approval_rejection_workflow(agent):
    req = agent.request_approval(
        title="Purchase new SaaS seats",
        target_object="saas:licenses",
        requester_id="dan",
    )
    rejected = agent.reject_approval(req.id, "cto", reason="Not in Q4 budget")
    assert rejected.status == ApprovalStatus.REJECTED


def test_invalid_approval_transition_raises(agent):
    req = agent.request_approval(
        title="Deploy to prod",
        target_object="app:api",
        requester_id="eve",
    )
    agent.grant_approval(req.id, "lead")

    # Attempt to transition GRANTED approval back to REQUESTED or REJECTED
    with pytest.raises(InvalidApprovalTransitionError):
        agent.validate_approval_transition(ApprovalStatus.GRANTED, ApprovalStatus.REQUESTED)


def test_invalid_governance_transition_raises(agent):
    # Transitioning CLOSED to REMEDIATION_REQUIRED directly is invalid
    with pytest.raises(InvalidGovernanceTransitionError):
        agent.validate_governance_transition(ViolationStatus.CLOSED, ViolationStatus.REMEDIATION_REQUIRED)


# -----------------------------------------------------------------------------
# O, P, Q: Evidence Preservation, Provenance & Correlation
# -----------------------------------------------------------------------------

def test_evidence_and_provenance_preservation(agent, repo):
    evt = _make_event(
        OrganizationEventType.POLICY_VIOLATION,
        "Customer PII detected in unsecured public channel",
        metadata={"policy_id": "DATA-001", "severity": "high"},
        evidence=["slack-message-ts-12345678", "dlp-scanner-rule-7"],
    )

    res = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="dlp-alert-1",
        correlation_id="corr-dlp-incident-1",
    )

    finding = repo.find_finding(res.finding.id)
    assert finding is not None
    assert "slack-message-ts-12345678" in finding.evidence
    assert "dlp-scanner-rule-7" in finding.evidence
    assert "dlp-alert-1" in finding.evidence
    assert finding.source_type == "slack"
    assert finding.source_event_id == "dlp-alert-1"
    assert finding.correlation_id == "corr-dlp-incident-1"


# -----------------------------------------------------------------------------
# R: Operations Agent Coordination for Remediation
# -----------------------------------------------------------------------------

def test_operations_agent_remediation_coordination(agent, ops_agent):
    evt = _make_event(
        OrganizationEventType.POLICY_VIOLATION,
        "Direct production SSH access without MFA",
        metadata={
            "policy_id": "SEC-001",
            "severity": "critical",
            "remediation_required": True,
        },
    )

    res = agent.process_event(
        evt,
        source_type="audit",
        source_event_id="sec-mfa-1",
        correlation_id="corr-mfa-1",
    )

    assert res.remediation_required is True
    # Verify OperationsAgent received a remediation risk event
    assert len(ops_agent.processed_events) == 1
    event_dispatched, kwargs = ops_agent.processed_events[0]
    assert event_dispatched.event_type == OrganizationEventType.RISK_IDENTIFIED
    assert "Governance Remediation" in event_dispatched.summary
    assert kwargs.get("correlation_id") == "corr-mfa-1"


# -----------------------------------------------------------------------------
# S, T: Feature Flag & Unsupported Event Behavior
# -----------------------------------------------------------------------------

def test_feature_flag_disabled_behavior(repo):
    disabled_agent = GovernanceAgent(repository=repo, enabled=False)
    evt = _make_event(OrganizationEventType.POLICY_VIOLATION, "Breach")
    res = disabled_agent.process_event(evt)
    assert res.operation == "disabled"


def test_unsupported_event_behavior(agent):
    evt = _make_event(OrganizationEventType.QUESTION_ASKED, "What is the policy?")
    with pytest.raises(UnsupportedGovernanceEventError):
        agent.process_event(evt, raise_on_unsupported=True)

    # Ignored cleanly in non-strict mode
    res = agent.process_event(evt, raise_on_unsupported=False)
    assert res.operation == "ignored"
    assert res.idempotent is True


# -----------------------------------------------------------------------------
# U: Evidence Retrieval & Ask
# -----------------------------------------------------------------------------

def test_retrieve_evidence_and_ask(agent, repo):
    evt = _make_event(
        OrganizationEventType.POLICY_VIOLATION,
        "Unapproved expenditure on GPU instances",
        metadata={"policy_id": "FIN-001", "severity": "medium"},
    )
    agent.process_event(evt, source_type="aws", source_event_id="exp-1")

    q = Question(text="What compliance violation happened with FIN-001?")
    evidence = agent.retrieve_evidence(q)
    assert len(evidence) >= 1
    assert any("FIN-001" in ev for ev in evidence)

    ans = agent.ask(q)
    assert ans["question"] == q.text
    assert len(ans["evidence"]) >= 1
    assert ans["governance_state"]["open_violations_count"] == 1


def test_evaluate_selects_most_restrictive_matching_policy(agent, repo):
    repo.save_policy(
        Policy.create(
            policy_id="TEST-LOW",
            name="Low Priority Policy",
            description="Less restrictive matching policy",
            scope=PolicyScope.GENERAL,
            severity=PolicySeverity.LOW,
            enforcement_mode=PolicyEnforcementMode.ADVISORY,
            condition_keywords=["priority-test"],
        )
    )
    repo.save_policy(
        Policy.create(
            policy_id="TEST-CRITICAL",
            name="Critical Security Policy",
            description="Most restrictive matching policy",
            scope=PolicyScope.GENERAL,
            severity=PolicySeverity.CRITICAL,
            enforcement_mode=PolicyEnforcementMode.BLOCKING,
            condition_keywords=["priority-test"],
            requires_approval=True,
        )
    )

    result = agent.evaluate("priority-test operation")

    assert result.policy_id == "TEST-CRITICAL"
    assert result.evaluation_status == PolicyEvaluationStatus.APPROVAL_REQUIRED
