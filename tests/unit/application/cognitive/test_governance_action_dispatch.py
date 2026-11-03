"""
Unit tests for POLIS Phase 3.3 Stage B4: Governance Action Dispatch and Authorization Reliability.

Covers:
1. Valid approval request creation.
2. Missing approval title.
3. Missing target object.
4. Authenticated requester identity is used.
5. Planner cannot override requester identity.
6. Valid approval grant by an authorized approver, if a verified authorization path exists.
7. Unauthorized approval grant is rejected.
8. Valid approval rejection by an authorized approver, if supported.
9. Unauthorized approval rejection is rejected.
10. Missing approval ID.
11. Missing rejection reason, if required by the domain.
12. Invalid lifecycle transitions.
13. Approval not found.
14. Successful mutation clears pending state.
15. Failed mutation preserves pending state.
16. No silent fall-through after failed governance mutations.
17. Read-only governance queries remain unaffected.
18. B1 task dispatch remains unaffected.
19. B2 calendar dispatch remains unaffected.
20. B3 reminder dispatch remains unaffected.
21. Unrelated intents are not intercepted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from domain.calendar.enums import CalendarAudienceType
from domain.calendar.repositories import InMemoryCalendarRepository
from domain.governance.entities.approval import ApprovalRequest
from domain.governance.entities.policy import Policy
from domain.governance.enums import ApprovalStatus, PolicyScope
from domain.governance.repositories.in_memory_governance_repository import (
    InMemoryGovernanceRepository,
)
from domain.operations import (
    InMemoryOperationalItemRepository,
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.reasoning.value_objects import (
    ActionType,
    Answer,
    CognitivePlan,
    ConversationContext,
    ExecutionStep,
    ExtractedEntities,
    IntentCategory,
    PendingOperation,
    Question,
    TargetAgent,
)
from domain.reminders.repositories import InMemoryReminderRepository
from domain.reminders.services import ReminderService
from application.calendar import CalendarAgent, CalendarService
from application.cognitive import SimpleCognitiveEngine
from application.governance import GovernanceAgent
from application.operations import (
    OperationalItemService,
    OperationsAgent,
)


@pytest.fixture
def gov_repo() -> InMemoryGovernanceRepository:
    return InMemoryGovernanceRepository(seed_default_policies=True)


@pytest.fixture
def op_repo() -> InMemoryOperationalItemRepository:
    return InMemoryOperationalItemRepository()


@pytest.fixture
def op_service(op_repo) -> OperationalItemService:
    return OperationalItemService(op_repo)


@pytest.fixture
def reminder_repo() -> InMemoryReminderRepository:
    return InMemoryReminderRepository()


@pytest.fixture
def reminder_service(reminder_repo) -> ReminderService:
    return ReminderService(reminder_repo)


@pytest.fixture
def operations_agent(op_repo, op_service, reminder_service) -> OperationsAgent:
    return OperationsAgent(
        repository=op_repo,
        operational_item_service=op_service,
        reminder_service=reminder_service,
    )


@pytest.fixture
def cal_repo() -> InMemoryCalendarRepository:
    return InMemoryCalendarRepository()


@pytest.fixture
def cal_service(cal_repo) -> CalendarService:
    mock_audience = MagicMock()
    mock_audience.resolve.return_value = MagicMock(
        audience_type=CalendarAudienceType.TEAM,
        resolved_slack_user_ids=["U_ALICE", "U_BOB"],
        slack_channel_id=None,
        display_name="Engineering",
    )
    return CalendarService(
        repository=cal_repo,
        audience_service=mock_audience,
        default_timezone="Asia/Kolkata",
    )


@pytest.fixture
def calendar_agent(cal_service) -> CalendarAgent:
    mock_identity = MagicMock()
    mock_identity.resolve_user_id.side_effect = lambda x: f"U_{x.upper()}"
    return CalendarAgent(
        service=cal_service,
        default_timezone="Asia/Kolkata",
        identity_resolver=mock_identity,
    )


class SimpleApproverAuthorizationService:
    """Mock authoritative approver verification service for testing."""

    def __init__(self, authorized_approvers: set[str]) -> None:
        self.authorized_approvers = set(authorized_approvers)

    def is_authorized_approver(self, user_id: str, approval: ApprovalRequest) -> bool:
        if not user_id:
            return False
        # Self-approval prohibited
        if approval.requester_id and approval.requester_id.strip() == user_id.strip():
            return False
        return user_id.strip() in self.authorized_approvers


@pytest.fixture
def approver_auth_service() -> SimpleApproverAuthorizationService:
    return SimpleApproverAuthorizationService(authorized_approvers={"U_SEC_LEAD", "U_CTO"})


@pytest.fixture
def gov_agent_with_auth(gov_repo, approver_auth_service) -> GovernanceAgent:
    return GovernanceAgent(
        repository=gov_repo,
        approver_authorization_service=approver_auth_service,
    )


@pytest.fixture
def gov_agent_default(gov_repo) -> GovernanceAgent:
    # Default without approver authorization service (production baseline)
    return GovernanceAgent(repository=gov_repo)


def _make_governance_plan(
    action: str,
    action_type: ActionType,
    parameters: dict,
    intent: IntentCategory = IntentCategory.GOVERNANCE_ACTION,
    missing_fields: list[str] | None = None,
    requires_clarification: bool = False,
    clarification_prompt: str | None = None,
) -> CognitivePlan:
    step = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action=action,
        action_type=action_type,
        parameters=parameters,
    )
    return CognitivePlan(
        request_id="test_plan_gov_123",
        original_message="Test governance request",
        intent=intent,
        intent_confidence=0.95,
        requested_outcome=f"Execute {action}",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.GOVERNANCE_AGENT],
        execution_steps=[step],
        missing_information=missing_fields or [],
        requires_clarification=requires_clarification,
        clarification_prompt=clarification_prompt,
        action_required=not requires_clarification,
        risk_level="medium",
    )


def _make_engine(
    gov_agent: GovernanceAgent | None,
    operations_agent: OperationsAgent | None = None,
    calendar_agent: CalendarAgent | None = None,
    qa_mock: MagicMock | None = None,
) -> SimpleCognitiveEngine:
    mock_pipeline = MagicMock()
    if qa_mock is None:
        qa_mock = MagicMock()
        qa_mock.answer.return_value = Answer(text="General answer", confidence=0.8)
        qa_mock.retrieve_evidence.return_value = ["Org evidence"]
        qa_mock.answer_from_evidence.return_value = Answer(text="Synthesized answer", confidence=0.85)

    return SimpleCognitiveEngine(
        pipeline=mock_pipeline,
        question_answering=qa_mock,
        governance_agent=gov_agent,
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
    )


# =============================================================================
# 1. Valid Approval Request Creation
# =============================================================================

def test_valid_approval_request_creation(gov_agent_default, gov_repo):
    engine = _make_engine(gov_agent_default)
    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Request approval for hotfix deployment", context=context)

    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Emergency hotfix deployment to production",
            "target_object": "service:payment-gateway",
            "policy_id": "DEP-001",
            "notes": "Fixes critical checkout timeout bug",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "✅ Approval request submitted successfully." in ans.text
    assert "Title: Emergency hotfix deployment to production" in ans.text
    assert "Target Object: service:payment-gateway" in ans.text
    assert "Status: requested" in ans.text
    assert "Requester: U_ALICE" in ans.text
    assert "Policy ID: DEP-001" in ans.text
    assert ans.clear_pending is True

    # Check persistence
    pending = gov_repo.list_pending_approvals()
    assert len(pending) == 1
    req = pending[0]
    assert req.title == "Emergency hotfix deployment to production"
    assert req.target_object == "service:payment-gateway"
    assert req.requester_id == "U_ALICE"
    assert req.policy_id == "DEP-001"
    assert req.status == ApprovalStatus.REQUESTED


# =============================================================================
# 2. Missing Approval Title
# =============================================================================

def test_missing_approval_title(gov_agent_default):
    engine = _make_engine(gov_agent_default)
    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Request approval for target", context=context)

    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "",
            "target_object": "service:payment-gateway",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "valid approval title is required" in ans.text
    assert ans.clear_pending is False


# =============================================================================
# 3. Missing Target Object
# =============================================================================

def test_missing_target_object(gov_agent_default):
    engine = _make_engine(gov_agent_default)
    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Request approval for title", context=context)

    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Emergency hotfix",
            "target_object": "",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "valid target object or resource is required" in ans.text
    assert ans.clear_pending is False


# =============================================================================
# 4. Authenticated Requester Identity is Used
# =============================================================================

def test_authenticated_requester_identity_is_used(gov_agent_default, gov_repo):
    engine = _make_engine(gov_agent_default)
    context = ConversationContext(user_id="U_AUTHENTICATED_USER", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Request approval", context=context)

    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Access request",
            "target_object": "db:analytics-replica",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.clear_pending is True
    pending = gov_repo.list_pending_approvals()
    assert pending[0].requester_id == "U_AUTHENTICATED_USER"


# =============================================================================
# 5. Planner Cannot Override Requester Identity
# =============================================================================

def test_planner_cannot_override_requester_identity(gov_agent_default, gov_repo):
    engine = _make_engine(gov_agent_default)
    context = ConversationContext(user_id="U_GENUINE_CALLER", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Request approval as someone else", context=context)

    # Malicious planner parameter attempting to impersonate CTO
    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Drop production database",
            "target_object": "db:production-primary",
            "requester_id": "U_CTO_IMPERSONATION",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.clear_pending is True
    pending = gov_repo.list_pending_approvals()
    assert len(pending) == 1
    # Must strictly use genuine caller context, NOT the planner parameter
    assert pending[0].requester_id == "U_GENUINE_CALLER"
    assert "Requester: U_GENUINE_CALLER" in ans.text


# =============================================================================
# 6. Valid Approval Grant by an Authorized Approver
# =============================================================================

def test_valid_approval_grant_by_authorized_approver(gov_agent_with_auth, gov_repo):
    engine = _make_engine(gov_agent_with_auth)
    # Create existing approval
    existing = gov_agent_with_auth.request_approval(
        title="Deploy v2.4.0",
        target_object="service:api",
        requester_id="U_ALICE",
    )
    assert existing.status == ApprovalStatus.REQUESTED

    # Authorized approver U_SEC_LEAD grants it
    context = ConversationContext(user_id="U_SEC_LEAD", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text=f"Grant approval {existing.id}", context=context)

    plan = _make_governance_plan(
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={
            "approval_id": existing.id,
            "notes": "Verified security scan passes.",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "✅ Approval request granted successfully." in ans.text
    assert f"ID: {existing.id}" in ans.text
    assert "Status: granted" in ans.text
    assert "Approver: U_SEC_LEAD" in ans.text
    assert ans.clear_pending is True

    # Check persistence
    saved = gov_repo.find_approval(existing.id)
    assert saved.status == ApprovalStatus.GRANTED
    assert saved.approver_id == "U_SEC_LEAD"
    assert saved.granted_at is not None
    assert "Verified security scan passes." in saved.notes


# =============================================================================
# 7. Unauthorized Approval Grant is Rejected
# =============================================================================

def test_unauthorized_approval_grant_is_rejected(gov_agent_with_auth, gov_repo):
    engine = _make_engine(gov_agent_with_auth)
    existing = gov_agent_with_auth.request_approval(
        title="Deploy v2.4.0",
        target_object="service:api",
        requester_id="U_ALICE",
    )

    # Unauthorized user U_MALLORY attempts to grant
    context = ConversationContext(user_id="U_MALLORY", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text=f"Grant approval {existing.id}", context=context)

    plan = _make_governance_plan(
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": existing.id},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "Unauthorized" in ans.text
    assert "U_MALLORY" in ans.text
    assert ans.clear_pending is False

    # State in repository must remain unchanged
    saved = gov_repo.find_approval(existing.id)
    assert saved.status == ApprovalStatus.REQUESTED
    assert saved.approver_id is None


def test_self_approval_grant_is_rejected(gov_agent_with_auth, gov_repo):
    engine = _make_engine(gov_agent_with_auth)
    # Even if requester U_SEC_LEAD is an approver, self-approval is rejected
    existing = gov_agent_with_auth.request_approval(
        title="Deploy v2.4.0",
        target_object="service:api",
        requester_id="U_SEC_LEAD",
    )

    context = ConversationContext(user_id="U_SEC_LEAD", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text=f"Grant approval {existing.id}", context=context)

    plan = _make_governance_plan(
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": existing.id},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "Unauthorized" in ans.text
    assert ans.clear_pending is False
    saved = gov_repo.find_approval(existing.id)
    assert saved.status == ApprovalStatus.REQUESTED


# =============================================================================
# 8. Valid Approval Rejection by an Authorized Approver
# =============================================================================

def test_valid_approval_rejection_by_authorized_approver(gov_agent_with_auth, gov_repo):
    engine = _make_engine(gov_agent_with_auth)
    existing = gov_agent_with_auth.request_approval(
        title="AWS Budget scale up",
        target_object="cloud:aws-resources",
        requester_id="U_CAROL",
    )

    context = ConversationContext(user_id="U_CTO", channel_id="C_MGMT", thread_ts="1234.56")
    question = Question(text=f"Reject approval {existing.id}", context=context)

    plan = _make_governance_plan(
        action="reject_approval",
        action_type=ActionType.UPDATE,
        parameters={
            "approval_id": existing.id,
            "reason": "Exceeds quarterly infrastructure allocation.",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "✅ Approval request rejected successfully." in ans.text
    assert "Status: rejected" in ans.text
    assert "Approver: U_CTO" in ans.text
    assert ans.clear_pending is True

    saved = gov_repo.find_approval(existing.id)
    assert saved.status == ApprovalStatus.REJECTED
    assert saved.approver_id == "U_CTO"
    assert "Exceeds quarterly infrastructure allocation." in saved.notes


# =============================================================================
# 9. Unauthorized Approval Rejection is Rejected
# =============================================================================

def test_unauthorized_approval_rejection_is_rejected(gov_agent_with_auth, gov_repo):
    engine = _make_engine(gov_agent_with_auth)
    existing = gov_agent_with_auth.request_approval(
        title="AWS Budget scale up",
        target_object="cloud:aws-resources",
        requester_id="U_CAROL",
    )

    context = ConversationContext(user_id="U_UNAUTHORIZED", channel_id="C_MGMT", thread_ts="1234.56")
    question = Question(text=f"Reject approval {existing.id}", context=context)

    plan = _make_governance_plan(
        action="reject_approval",
        action_type=ActionType.UPDATE,
        parameters={
            "approval_id": existing.id,
            "reason": "I disagree with this spend.",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "Unauthorized" in ans.text
    assert "U_UNAUTHORIZED" in ans.text
    assert ans.clear_pending is False

    saved = gov_repo.find_approval(existing.id)
    assert saved.status == ApprovalStatus.REQUESTED


# =============================================================================
# 10. Missing Approval ID
# =============================================================================

def test_missing_approval_id(gov_agent_with_auth):
    engine = _make_engine(gov_agent_with_auth)
    context = ConversationContext(user_id="U_SEC_LEAD", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Grant approval", context=context)

    plan = _make_governance_plan(
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": ""},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "valid approval ID is required" in ans.text
    assert ans.clear_pending is False


# =============================================================================
# 11. Missing Rejection Reason
# =============================================================================

def test_missing_rejection_reason(gov_agent_with_auth):
    engine = _make_engine(gov_agent_with_auth)
    context = ConversationContext(user_id="U_CTO", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Reject approval app-123", context=context)

    plan = _make_governance_plan(
        action="reject_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": "app-123", "reason": ""},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "meaningful rejection reason is required" in ans.text
    assert ans.clear_pending is False


# =============================================================================
# 12. Invalid Lifecycle Transitions
# =============================================================================

def test_invalid_lifecycle_transition_raises_user_safe_error(gov_agent_with_auth, gov_repo):
    engine = _make_engine(gov_agent_with_auth)
    # Already GRANTED approval
    req = gov_agent_with_auth.request_approval(
        title="Deploy app",
        target_object="service:api",
        requester_id="U_ALICE",
    )
    gov_agent_with_auth.grant_approval(req.id, "U_SEC_LEAD")

    # Attempt to REJECT an already GRANTED approval
    context = ConversationContext(user_id="U_CTO", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text=f"Reject approval {req.id}", context=context)

    plan = _make_governance_plan(
        action="reject_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": req.id, "reason": "Changed my mind"},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "Cannot reject approval" in ans.text
    assert "Cannot transition approval from 'granted' to 'rejected'" in ans.text
    assert ans.clear_pending is False


# =============================================================================
# 13. Approval Not Found
# =============================================================================

def test_approval_not_found(gov_agent_with_auth):
    engine = _make_engine(gov_agent_with_auth)
    context = ConversationContext(user_id="U_SEC_LEAD", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Grant approval missing-app-999", context=context)

    plan = _make_governance_plan(
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": "missing-app-999"},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "approval request 'missing-app-999' was not found" in ans.text
    assert ans.clear_pending is False


# =============================================================================
# 14. Successful Mutation Clears Pending State
# =============================================================================

def test_successful_mutation_clears_pending_state(gov_agent_default):
    engine = _make_engine(gov_agent_default)
    pending_op = PendingOperation(
        operation_id="op_gov_test",
        intent=IntentCategory.GOVERNANCE_ACTION,
        target_agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        collected_entities={"title": "DB Access"},
        missing_fields=["target_object"],
        clarification_question="What is the target object?",
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="1234.56",
        created_at_iso="2026-10-30T10:00:00+00:00",
        expires_at_iso="2026-10-30T10:15:00+00:00",
    )
    context = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="1234.56",
        pending_operation=pending_op.model_dump(),
    )
    question = Question(text="db:prod-primary", context=context)

    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "DB Access",
            "target_object": "db:prod-primary",
        },
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.clear_pending is True
    assert "submitted successfully" in ans.text


# =============================================================================
# 15. Failed Mutation Preserves Pending State
# =============================================================================

def test_failed_mutation_preserves_pending_state(gov_agent_default):
    engine = _make_engine(gov_agent_default)
    pending_op = PendingOperation(
        operation_id="op_gov_test",
        intent=IntentCategory.GOVERNANCE_ACTION,
        target_agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        collected_entities={},
        missing_fields=["title", "target_object"],
        clarification_question="Please provide title",
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="1234.56",
        created_at_iso="2026-10-30T10:00:00+00:00",
        expires_at_iso="2026-10-30T10:15:00+00:00",
    )
    context = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="1234.56",
        pending_operation=pending_op.model_dump(),
    )
    question = Question(text="incomplete", context=context)

    # Missing target object
    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={"title": "Some title", "target_object": ""},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.clear_pending is False
    assert "valid target object or resource is required" in ans.text


# =============================================================================
# 16. No Silent Fall-Through After Failed Governance Mutations
# =============================================================================

def test_no_silent_fall_through_after_failed_governance_mutation(gov_agent_default):
    qa_mock = MagicMock()
    qa_mock.retrieve_evidence = MagicMock()
    qa_mock.answer_from_evidence = MagicMock()
    engine = _make_engine(gov_agent_default, qa_mock=qa_mock)

    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Request approval", context=context)

    # Missing target object
    plan = _make_governance_plan(
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={"title": "Some Title", "target_object": ""},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    # Must NOT fall through to QA evidence retrieval
    qa_mock.retrieve_evidence.assert_not_called()
    qa_mock.answer_from_evidence.assert_not_called()
    assert "valid target object or resource is required" in ans.text


# =============================================================================
# 17. Read-Only Governance Queries Remain Unaffected
# =============================================================================

def test_read_only_governance_queries_remain_unaffected(gov_agent_default):
    qa_mock = MagicMock()
    qa_mock.retrieve_evidence.return_value = ["Policy SEC-001 evidence"]
    qa_mock.answer_from_evidence.return_value = Answer(
        text="According to policy SEC-001, production database access requires explicit authorization.",
        confidence=0.9,
    )
    engine = _make_engine(gov_agent_default, qa_mock=qa_mock)

    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="What is the policy for production database access?", context=context)

    plan = CognitivePlan(
        request_id="read_plan_1",
        original_message=question.text,
        intent=IntentCategory.KNOWLEDGE_QUERY,
        intent_confidence=0.9,
        requested_outcome="Query compliance and governance policies",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.GOVERNANCE_AGENT],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.GOVERNANCE_AGENT,
                action="query_governance",
                action_type=ActionType.READ,
                parameters={"query": question.text},
            )
        ],
        missing_information=[],
        requires_clarification=False,
        action_required=False,
        risk_level="low",
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "According to policy SEC-001" in ans.text
    # Evidence from QA service was called
    qa_mock.answer_from_evidence.assert_called_once()


# =============================================================================
# 18. B1 Task Dispatch Remains Unaffected
# =============================================================================

def test_b1_task_dispatch_remains_unaffected(gov_agent_default, operations_agent, op_repo):
    engine = _make_engine(gov_agent_default, operations_agent=operations_agent)
    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Create task to review audit logs", context=context)

    plan = CognitivePlan(
        request_id="task_plan_1",
        original_message=question.text,
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=0.95,
        requested_outcome="Create task",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.OPERATIONS_AGENT,
                action="create_task",
                action_type=ActionType.CREATE,
                parameters={
                    "summary": "Review audit logs",
                    "assignee": "U_BOB",
                    "priority": "high",
                },
            )
        ],
        missing_information=[],
        requires_clarification=False,
        action_required=True,
        risk_level="low",
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.clear_pending is True
    assert "Review audit logs" in ans.text

    tasks = [item for item in op_repo._items.values() if item.item_type == OperationalItemType.TASK]
    assert len(tasks) == 1
    assert tasks[0].summary == "Review audit logs"


# =============================================================================
# 19. B2 Calendar Dispatch Remains Unaffected
# =============================================================================

def test_b2_calendar_dispatch_remains_unaffected(gov_agent_default, calendar_agent, cal_repo):
    engine = _make_engine(gov_agent_default, calendar_agent=calendar_agent)
    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Schedule sprint sync tomorrow at 10am", context=context)

    plan = CognitivePlan(
        request_id="cal_plan_1",
        original_message=question.text,
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=0.95,
        requested_outcome="Schedule calendar event",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.CALENDAR_AGENT],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.CALENDAR_AGENT,
                action="create_event",
                action_type=ActionType.CREATE,
                parameters={
                    "title": "Sprint Sync",
                    "start_time": "2026-11-01T10:00:00+05:30",
                    "audience_type": "team",
                    "audience_identifier": "engineering",
                },
            )
        ],
        missing_information=[],
        requires_clarification=False,
        action_required=True,
        risk_level="low",
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.clear_pending is True
    assert "Sprint Sync" in ans.text

    entries = cal_repo.list_entries()
    assert len(entries) == 1
    assert entries[0].title == "Sprint Sync"
    assert entries[0].creator_id == "U_ALICE"


# =============================================================================
# 20. B3 Reminder Dispatch Remains Unaffected
# =============================================================================

def test_b3_reminder_dispatch_remains_unaffected(
    gov_agent_default, operations_agent, op_repo, reminder_repo
):
    engine = _make_engine(gov_agent_default, operations_agent=operations_agent)
    task = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Security compliance audit",
        owner_id="U_BOB",
    )
    op_repo.save(task)

    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="Set reminder for task", context=context)

    plan = CognitivePlan(
        request_id="rem_plan_1",
        original_message=question.text,
        intent=IntentCategory.REMINDER_ACTION,
        intent_confidence=0.95,
        requested_outcome="Schedule task reminder",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.REMINDER_SERVICE],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.REMINDER_SERVICE,
                action="create_reminder",
                action_type=ActionType.CREATE,
                parameters={
                    "task_id": str(task.identifier.graph_id),
                    "target_user_id": "U_BOB",
                    "time_1": "09:00",
                    "time_2": "17:00",
                    "timezone_name": "UTC",
                },
            )
        ],
        missing_information=[],
        requires_clarification=False,
        action_required=True,
        risk_level="low",
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.clear_pending is True
    assert "Successfully scheduled task reminder" in ans.text
    assert len(reminder_repo.list_all()) == 1


# =============================================================================
# 21. Unrelated Intents are Not Intercepted
# =============================================================================

def test_unrelated_intents_are_not_intercepted(gov_agent_default):
    qa_mock = MagicMock()
    qa_mock.answer.return_value = Answer(
        text="Hello! How can I help you today?",
        confidence=1.0,
        is_conversational=True,
    )
    engine = _make_engine(gov_agent_default, qa_mock=qa_mock)

    context = ConversationContext(user_id="U_ALICE", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text="hello", context=context)

    plan = CognitivePlan(
        request_id="gen_plan_1",
        original_message=question.text,
        intent=IntentCategory.GENERAL_CONVERSATION,
        intent_confidence=1.0,
        requested_outcome="Acknowledge conversational pleasantry or greeting",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.GENERAL_REASONER],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.GENERAL_REASONER,
                action="conversation",
                action_type=ActionType.READ,
                parameters={"query": question.text},
            )
        ],
        missing_information=[],
        requires_clarification=False,
        action_required=False,
        risk_level="low",
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert ans.text == "Hello! How can I help you today?"
    qa_mock.answer.assert_called_once_with(question)


# =============================================================================
# Production Baseline: Default Agent Safely Rejects Grant/Reject
# =============================================================================

def test_default_agent_safely_rejects_grant_without_configured_authorization(
    gov_agent_default, gov_repo
):
    engine = _make_engine(gov_agent_default)
    existing = gov_agent_default.request_approval(
        title="Deploy v2.4.0",
        target_object="service:api",
        requester_id="U_ALICE",
    )

    context = ConversationContext(user_id="U_ADMIN_CLAIM", channel_id="C_DEV", thread_ts="1234.56")
    question = Question(text=f"Grant approval {existing.id}", context=context)

    plan = _make_governance_plan(
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": existing.id},
    )
    engine.planner.plan = MagicMock(return_value=plan)

    ans = engine.ask(question)
    assert "POLIS does not expose an approver authorization mechanism in this conversational channel" in ans.text
    assert ans.clear_pending is False
    saved = gov_repo.find_approval(existing.id)
    assert saved.status == ApprovalStatus.REQUESTED
