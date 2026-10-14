from domain.governance import (
    ApprovalRequest,
    ApprovalStatus,
    ComplianceStatus,
    GovernanceFinding,
    InMemoryGovernanceRepository,
    Policy,
    PolicyEnforcementMode,
    PolicyScope,
    PolicySeverity,
    ViolationStatus,
)
from domain.governance.repositories.governance_repository import GovernanceRepository
from .connection import SessionLocal
from .models import (
    GovernanceApprovalModel,
    GovernanceFindingModel,
    GovernancePolicyModel,
)


class PostgreSQLGovernanceRepository(GovernanceRepository):
    """PostgreSQL-backed repository for governance policies, approvals, and findings."""

    def __init__(self, seed_default_policies: bool = True) -> None:
        if seed_default_policies:
            defaults = InMemoryGovernanceRepository()
            for policy in defaults.list_policies():
                if self.find_policy(policy.policy_id) is None:
                    self.save_policy(policy)

    def find_policy(self, policy_id: str) -> Policy | None:
        with SessionLocal() as session:
            record = session.get(GovernancePolicyModel, policy_id)
            return self._to_policy(record) if record else None

    def list_policies(
        self, scope: PolicyScope | None = None
    ) -> list[Policy]:
        with SessionLocal() as session:
            query = session.query(GovernancePolicyModel)
            if scope is not None:
                query = query.filter(GovernancePolicyModel.scope == scope.value)
            records = query.order_by(GovernancePolicyModel.policy_id).all()
            return [self._to_policy(record) for record in records]

    def save_policy(self, policy: Policy) -> Policy:
        with SessionLocal() as session:
            record = session.get(GovernancePolicyModel, policy.policy_id)
            if record is None:
                record = GovernancePolicyModel(policy_id=policy.policy_id)
                session.add(record)

            record.name = policy.name
            record.description = policy.description
            record.scope = policy.scope.value
            record.severity = policy.severity.value
            record.enforcement_mode = policy.enforcement_mode.value
            record.authority = policy.authority
            record.requires_approval = policy.requires_approval
            record.rule_description = policy.rule_description
            record.condition_keywords = list(policy.condition_keywords)
            record.effective_date = policy.effective_date
            record.metadata_ = dict(policy.metadata)

            session.commit()
            session.refresh(record)
            return self._to_policy(record)

    def find_approval(self, approval_id: str) -> ApprovalRequest | None:
        with SessionLocal() as session:
            record = session.get(GovernanceApprovalModel, approval_id)
            return self._to_approval(record) if record else None

    def find_approval_by_correlation(
        self, correlation_id: str
    ) -> ApprovalRequest | None:
        if not correlation_id:
            return None

        with SessionLocal() as session:
            record = (
                session.query(GovernanceApprovalModel)
                .filter(GovernanceApprovalModel.correlation_id == correlation_id)
                .order_by(GovernanceApprovalModel.requested_at)
                .first()
            )
            return self._to_approval(record) if record else None

    def find_approval_by_source_event(
        self, source_type: str, source_event_id: str
    ) -> ApprovalRequest | None:
        if not source_event_id:
            return None

        with SessionLocal() as session:
            query = session.query(GovernanceApprovalModel).filter(
                GovernanceApprovalModel.source_event_id == source_event_id
            )
            if source_type:
                query = query.filter(
                    GovernanceApprovalModel.source_type == source_type
                )
            record = query.order_by(GovernanceApprovalModel.requested_at).first()
            return self._to_approval(record) if record else None

    def save_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        with SessionLocal() as session:
            record = session.get(GovernanceApprovalModel, approval.id)
            if record is None:
                record = GovernanceApprovalModel(id=approval.id)
                session.add(record)

            record.title = approval.title
            record.target_object = approval.target_object
            record.requester_id = approval.requester_id
            record.status = approval.status.value
            record.policy_id = approval.policy_id
            record.approver_id = approval.approver_id
            record.source_event_id = approval.source_event_id
            record.source_type = approval.source_type
            record.correlation_id = approval.correlation_id
            record.evidence = list(approval.evidence)
            record.requested_at = approval.requested_at
            record.granted_at = approval.granted_at
            record.notes = approval.notes
            record.metadata_ = dict(approval.metadata)

            session.commit()
            session.refresh(record)
            return self._to_approval(record)

    def list_pending_approvals(self) -> list[ApprovalRequest]:
        with SessionLocal() as session:
            records = (
                session.query(GovernanceApprovalModel)
                .filter(
                    GovernanceApprovalModel.status.in_(
                        [ApprovalStatus.REQUESTED.value, ApprovalStatus.PENDING.value]
                    )
                )
                .order_by(GovernanceApprovalModel.requested_at)
                .all()
            )
            return [self._to_approval(record) for record in records]

    def find_finding(self, finding_id: str) -> GovernanceFinding | None:
        with SessionLocal() as session:
            record = session.get(GovernanceFindingModel, finding_id)
            return self._to_finding(record) if record else None

    def find_finding_by_source_event(
        self, source_type: str, source_event_id: str
    ) -> GovernanceFinding | None:
        if not source_event_id:
            return None

        with SessionLocal() as session:
            query = session.query(GovernanceFindingModel).filter(
                GovernanceFindingModel.source_event_id == source_event_id
            )
            if source_type:
                query = query.filter(
                    GovernanceFindingModel.source_type == source_type
                )
            record = query.order_by(GovernanceFindingModel.created_at).first()
            return self._to_finding(record) if record else None

    def find_finding_by_correlation(
        self, correlation_id: str
    ) -> list[GovernanceFinding]:
        if not correlation_id:
            return []

        with SessionLocal() as session:
            records = (
                session.query(GovernanceFindingModel)
                .filter(GovernanceFindingModel.correlation_id == correlation_id)
                .order_by(GovernanceFindingModel.created_at)
                .all()
            )
            return [self._to_finding(record) for record in records]

    def save_finding(self, finding: GovernanceFinding) -> GovernanceFinding:
        with SessionLocal() as session:
            record = session.get(GovernanceFindingModel, finding.id)
            if record is None:
                record = GovernanceFindingModel(id=finding.id)
                session.add(record)

            record.policy_id = finding.policy_id
            record.policy_name = finding.policy_name
            record.summary = finding.summary
            record.severity = finding.severity.value
            record.status = finding.status.value
            record.compliance_status = finding.compliance_status.value
            record.affected_object = finding.affected_object
            record.evidence = list(finding.evidence)
            record.source_event_id = finding.source_event_id
            record.source_type = finding.source_type
            record.correlation_id = finding.correlation_id
            record.confidence = finding.confidence
            record.authority = finding.authority
            record.created_at = finding.created_at
            record.updated_at = finding.updated_at
            record.remediation_required = finding.remediation_required
            record.metadata_ = dict(finding.metadata)

            session.commit()
            session.refresh(record)
            return self._to_finding(record)

    def list_findings(
        self, status: ViolationStatus | None = None
    ) -> list[GovernanceFinding]:
        with SessionLocal() as session:
            query = session.query(GovernanceFindingModel)
            if status is not None:
                query = query.filter(GovernanceFindingModel.status == status.value)
            records = query.order_by(GovernanceFindingModel.created_at).all()
            return [self._to_finding(record) for record in records]

    @staticmethod
    def _to_policy(record: GovernancePolicyModel) -> Policy:
        return Policy(
            policy_id=record.policy_id,
            name=record.name,
            description=record.description,
            scope=PolicyScope(record.scope),
            severity=PolicySeverity(record.severity),
            enforcement_mode=PolicyEnforcementMode(record.enforcement_mode),
            authority=record.authority,
            requires_approval=record.requires_approval,
            rule_description=record.rule_description,
            condition_keywords=list(record.condition_keywords or []),
            effective_date=record.effective_date,
            metadata=dict(record.metadata_ or {}),
        )

    @staticmethod
    def _to_approval(record: GovernanceApprovalModel) -> ApprovalRequest:
        return ApprovalRequest(
            id=record.id,
            title=record.title,
            target_object=record.target_object,
            requester_id=record.requester_id,
            status=ApprovalStatus(record.status),
            policy_id=record.policy_id,
            approver_id=record.approver_id,
            source_event_id=record.source_event_id,
            source_type=record.source_type,
            correlation_id=record.correlation_id,
            evidence=list(record.evidence or []),
            requested_at=record.requested_at,
            granted_at=record.granted_at,
            notes=record.notes,
            metadata=dict(record.metadata_ or {}),
        )

    @staticmethod
    def _to_finding(record: GovernanceFindingModel) -> GovernanceFinding:
        return GovernanceFinding(
            id=record.id,
            policy_id=record.policy_id,
            policy_name=record.policy_name,
            summary=record.summary,
            severity=PolicySeverity(record.severity),
            status=ViolationStatus(record.status),
            compliance_status=ComplianceStatus(record.compliance_status),
            affected_object=record.affected_object,
            evidence=list(record.evidence or []),
            source_event_id=record.source_event_id,
            source_type=record.source_type,
            correlation_id=record.correlation_id,
            confidence=record.confidence,
            authority=record.authority,
            created_at=record.created_at,
            updated_at=record.updated_at,
            remediation_required=record.remediation_required,
            metadata=dict(record.metadata_ or {}),
        )
