"""
Abstract repository interface for governance policies, approvals, and findings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.governance.entities.policy import Policy
from domain.governance.entities.approval import ApprovalRequest
from domain.governance.entities.finding import GovernanceFinding
from domain.governance.enums import (
    PolicyScope,
    ViolationStatus,
)


class GovernanceRepository(ABC):
    """
    Authoritative persistence interface for governance data.
    """

    # Policies
    @abstractmethod
    def find_policy(self, policy_id: str) -> Policy | None:
        raise NotImplementedError

    @abstractmethod
    def list_policies(self, scope: PolicyScope | None = None) -> list[Policy]:
        raise NotImplementedError

    @abstractmethod
    def save_policy(self, policy: Policy) -> Policy:
        raise NotImplementedError

    # Approvals
    @abstractmethod
    def find_approval(self, approval_id: str) -> ApprovalRequest | None:
        raise NotImplementedError

    @abstractmethod
    def find_approval_by_correlation(self, correlation_id: str) -> ApprovalRequest | None:
        raise NotImplementedError

    @abstractmethod
    def find_approval_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
    ) -> ApprovalRequest | None:
        raise NotImplementedError

    @abstractmethod
    def save_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        raise NotImplementedError

    @abstractmethod
    def list_pending_approvals(self) -> list[ApprovalRequest]:
        raise NotImplementedError

    # Findings / Violations
    @abstractmethod
    def find_finding(self, finding_id: str) -> GovernanceFinding | None:
        raise NotImplementedError

    @abstractmethod
    def find_finding_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
    ) -> GovernanceFinding | None:
        raise NotImplementedError

    @abstractmethod
    def find_finding_by_correlation(self, correlation_id: str) -> list[GovernanceFinding]:
        raise NotImplementedError

    @abstractmethod
    def save_finding(self, finding: GovernanceFinding) -> GovernanceFinding:
        raise NotImplementedError

    @abstractmethod
    def list_findings(self, status: ViolationStatus | None = None) -> list[GovernanceFinding]:
        raise NotImplementedError
