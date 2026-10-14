from uuid import uuid4

from domain.governance import (
    ApprovalRequest,
    GovernanceFinding,
    Policy,
    PolicyScope,
    PolicySeverity,
    PolicyEnforcementMode,
    ApprovalStatus,
    ComplianceStatus,
    ViolationStatus,
)
from infrastructure.database import (
    PostgreSQLGovernanceRepository,
    SessionLocal,
)
from infrastructure.database.models import (
    GovernancePolicyModel,
    GovernanceApprovalModel,
    GovernanceFindingModel,
)


def test_governance_repository_persists_entities_across_instances():
    repository = PostgreSQLGovernanceRepository(seed_default_policies=False)

    suffix = str(uuid4())
    policy_id = f"TEST-{suffix}"
    approval_id = str(uuid4())
    finding_id = str(uuid4())
    correlation_id = f"test-correlation-{suffix}"
    source_event_id = f"test-event-{suffix}"

    policy = Policy.create(
        policy_id=policy_id,
        name="Integration Test Policy",
        description="Policy persistence test",
        scope=PolicyScope.SECURITY,
        severity=PolicySeverity.HIGH,
        enforcement_mode=PolicyEnforcementMode.MANDATORY,
        requires_approval=True,
        rule_description="Test rule",
        condition_keywords=["integration-test"],
        metadata={"test_run": suffix},
    )
    approval = ApprovalRequest.create(
        title="Integration Test Approval",
        target_object="test deployment",
        requester_id="integration-test-user",
        id=approval_id,
        policy_id=policy_id,
        status=ApprovalStatus.PENDING,
        source_event_id=source_event_id,
        source_type="integration-test",
        correlation_id=correlation_id,
        evidence=["integration-test evidence"],
        metadata={"test_run": suffix},
    )
    finding = GovernanceFinding.create(
        policy_id=policy_id,
        policy_name=policy.name,
        summary="Integration test finding",
        severity=PolicySeverity.HIGH,
        id=finding_id,
        status=ViolationStatus.OPEN,
        compliance_status=ComplianceStatus.NON_COMPLIANT,
        affected_object="test deployment",
        evidence=["finding evidence"],
        source_event_id=source_event_id,
        source_type="integration-test",
        correlation_id=correlation_id,
        remediation_required=True,
        metadata={"test_run": suffix},
    )

    try:
        repository.save_policy(policy)
        repository.save_approval(approval)
        repository.save_finding(finding)

        # A fresh repository instance must retrieve the committed database state.
        reloaded = PostgreSQLGovernanceRepository(seed_default_policies=False)

        found_policy = reloaded.find_policy(policy_id)
        assert found_policy is not None
        assert found_policy.name == policy.name
        assert found_policy.scope == PolicyScope.SECURITY
        assert found_policy.condition_keywords == ["integration-test"]
        assert found_policy.metadata == {"test_run": suffix}

        found_approval = reloaded.find_approval(approval_id)
        assert found_approval is not None
        assert found_approval.status == ApprovalStatus.PENDING
        assert found_approval.correlation_id == correlation_id
        assert found_approval.evidence == ["integration-test evidence"]
        assert found_approval.metadata == {"test_run": suffix}

        found_finding = reloaded.find_finding(finding_id)
        assert found_finding is not None
        assert found_finding.status == ViolationStatus.OPEN
        assert found_finding.compliance_status == ComplianceStatus.NON_COMPLIANT
        assert found_finding.correlation_id == correlation_id
        assert found_finding.evidence == ["finding evidence"]
        assert found_finding.metadata == {"test_run": suffix}

        assert reloaded.find_approval_by_correlation(correlation_id) is not None
        assert reloaded.find_approval_by_source_event(
            "integration-test", source_event_id
        ) is not None
        assert reloaded.find_finding_by_source_event(
            "integration-test", source_event_id
        ) is not None
        assert len(reloaded.find_finding_by_correlation(correlation_id)) == 1

    finally:
        with SessionLocal() as session:
            for model, record_id in (
                (GovernanceFindingModel, finding_id),
                (GovernanceApprovalModel, approval_id),
                (GovernancePolicyModel, policy_id),
            ):
                record = session.get(model, record_id)
                if record is not None:
                    session.delete(record)
            session.commit()
