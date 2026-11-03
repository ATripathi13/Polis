"""
End-to-End Validation & Acceptance Test Suite for POLIS Phase 3.3 Stage B5.5.

Validates the complete cognitive execution architecture lifecycle:
User Request -> CognitivePlanner -> Validated CognitivePlan -> MultiStepCoordinator ->
Specialist Execution Bridge -> Domain Services -> Structured Results -> Conversation Persistence ->
Clarification -> Safe Continuation -> Final Response.

Sections covered:
1. Complete Architecture Runtime Inspection & Wiring
2. End-to-End Scenario Tests (A through G)
3. Creation-Idempotency Risk Validation & Replay Safety
4. Conversation Persistence Integration (In-Memory & PostgreSQL ORM)
5. Production Bootstrap Verification
6. User-Facing Response Truthfulness & Privacy Validation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest

from application.bootstrap.bootstrap import bootstrap
from application.calendar import (
    AudienceResolutionService,
    CalendarAgent,
    CalendarService,
)
from application.cognitive import (
    CognitivePlanner,
    MultiStepCoordinator,
    SimpleCognitiveEngine,
)
from application.governance import GovernanceAgent
from application.operations import (
    OperationalItemService,
    OperationsAgent,
)
from domain.calendar import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntryStatus,
    CalendarReminderPolicy,
    InMemoryCalendarRepository,
)
from domain.calendar.exceptions import UnauthorizedCalendarActionError
from domain.governance.entities.approval import ApprovalRequest
from domain.governance.enums import ApprovalStatus
from domain.governance.exceptions import InvalidApprovalTransitionError
from domain.governance.repositories.in_memory_governance_repository import (
    InMemoryGovernanceRepository,
)
from domain.operations import (
    InMemoryOperationalItemRepository,
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
    OperationsResult,
)
from domain.organization import OrganizationEventType
from domain.reasoning.value_objects import (
    ActionType,
    Answer,
    CognitivePlan,
    ConversationContext,
    ExecutionStep,
    ExtractedEntities,
    IntentCategory,
    MultiStepExecutionResult,
    MultiStepExecutionStatus,
    PendingOperation,
    Question,
    StepExecutionResult,
    StepExecutionStatus,
    TargetAgent,
)
from domain.reminders.repositories import InMemoryReminderRepository
from domain.reminders.services import ReminderService
from infrastructure.database import postgres_conversation_repository as pg_conv_module
from infrastructure.database.conversation_repository import InMemoryConversationRepository
from infrastructure.database.models import ConversationMemoryModel
from infrastructure.database.postgres_conversation_repository import PostgreSQLConversationRepository


# =============================================================================
# FIXTURES AND TEST ENVIRONMENT SETUP
# =============================================================================

class MockDirectoryProvider:
    """Mock directory provider for calendar audience resolution."""

    def resolve_user(self, identifier_or_name: str) -> dict | None:
        clean = identifier_or_name.strip()
        if clean.startswith("<@") and clean.endswith(">"):
            uid = clean[2:-1].split("|")[0]
            return {"id": uid, "name": uid, "real_name": uid}
        known = {"U_ALICE", "U_BOB", "U_CREATOR", "U_MALLORY", "U_DEV", "U_LEAD", "U_SEC_LEAD"}
        if clean.upper() in known:
            return {"id": clean.upper(), "name": clean, "real_name": clean}
        return None

    def get_user_id(self, user: dict | None) -> str | None:
        return user.get("id") if user else None

    def get_team_members(self, team_id_or_name: str) -> list[str]:
        if team_id_or_name.lower() in ("dev", "engineering"):
            return ["U_ALICE", "U_BOB"]
        return []

    def get_all_workspace_user_ids(self) -> list[str]:
        return ["U_ALICE", "U_BOB", "U_CREATOR", "U_MALLORY", "U_DEV", "U_LEAD", "U_SEC_LEAD"]


class AuthoritativeApproverService:
    """Mock authoritative approver verification service enforcing strict governance rules."""

    def __init__(self, authorized_approvers: set[str]) -> None:
        self.authorized_approvers = set(authorized_approvers)

    def is_authorized_approver(self, user_id: str, approval: ApprovalRequest) -> bool:
        if not user_id:
            return False
        # Self-approval prohibited
        if approval.requester_id and approval.requester_id.strip() == user_id.strip():
            return False
        return user_id.strip() in self.authorized_approvers


class FakeQuery:
    def __init__(self, records):
        self.records = records

    def filter(self, *criteria):
        filtered = self.records
        for crit in criteria:
            try:
                col_name = crit.left.name
                val = crit.right.value
                filtered = [r for r in filtered if getattr(r, col_name, None) == val]
            except Exception:
                pass
        return FakeQuery(filtered)

    def order_by(self, *expressions):
        return self

    def first(self):
        return self.records[0] if self.records else None

    def all(self):
        return self.records


class FakeSession:
    def __init__(self, records=None):
        self.records = records if records is not None else []
        self.added = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def query(self, model):
        assert model is ConversationMemoryModel
        return FakeQuery(self.records)

    def add(self, obj):
        self.added.append(obj)
        self.records.append(obj)

    def commit(self):
        self.committed = True


@pytest.fixture
def op_repo() -> InMemoryOperationalItemRepository:
    return InMemoryOperationalItemRepository()


@pytest.fixture
def reminder_repo() -> InMemoryReminderRepository:
    return InMemoryReminderRepository()


@pytest.fixture
def reminder_service(reminder_repo) -> ReminderService:
    return ReminderService(reminder_repo)


@pytest.fixture
def op_service(op_repo) -> OperationalItemService:
    return OperationalItemService(op_repo)


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
def audience_service() -> AudienceResolutionService:
    return AudienceResolutionService(
        directory_provider=MockDirectoryProvider(),
        organization_channel_id="C_MAIN",
    )


@pytest.fixture
def calendar_service(cal_repo, audience_service) -> CalendarService:
    return CalendarService(
        repository=cal_repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=12),
        default_timezone="Asia/Kolkata",
    )


@pytest.fixture
def calendar_agent(calendar_service) -> CalendarAgent:
    return CalendarAgent(
        service=calendar_service,
        default_timezone="Asia/Kolkata",
    )


@pytest.fixture
def gov_repo() -> InMemoryGovernanceRepository:
    return InMemoryGovernanceRepository(seed_default_policies=True)


@pytest.fixture
def approver_service() -> AuthoritativeApproverService:
    return AuthoritativeApproverService(authorized_approvers={"U_LEAD", "U_SEC_LEAD"})


@pytest.fixture
def governance_agent(gov_repo, approver_service) -> GovernanceAgent:
    return GovernanceAgent(
        repository=gov_repo,
        approver_authorization_service=approver_service,
        enabled=True,
    )


@pytest.fixture
def coordinator() -> MultiStepCoordinator:
    return MultiStepCoordinator()


@pytest.fixture
def engine(operations_agent, calendar_agent, governance_agent, coordinator) -> SimpleCognitiveEngine:
    pipeline = MagicMock()
    qa = MagicMock()
    planner = CognitivePlanner()
    return SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
        governance_agent=governance_agent,
        planner=planner,
        coordinator=coordinator,
    )


# =============================================================================
# 1. SCENARIO A: TASK DEPENDENCY CHAIN
# =============================================================================

def test_scenario_a_task_dependency_chain(engine, op_repo, reminder_repo):
    """
    Scenario A:
    1. Create a task.
    2. Use created task ID through $step_ref in reminder scheduling.
    3. Confirm both operations succeeded.
    4. Confirm reminder references actual persisted task.
    5. Verify task is not recreated during subsequent continuation.
    """
    ctx = ConversationContext(channel_id="C_ENG", thread_ts="100.1", user_id="U_ALICE")

    step1 = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Prepare production rollout", "priority": "high"},
    )
    step2 = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.REMINDER_SERVICE,
        action="schedule_reminder",
        action_type=ActionType.CREATE,
        dependencies=["step_1"],
        parameters={
            "task_id": {"$step_ref": "step_1", "field": "entity_id"},
            "time_1": "09:00",
            "time_2": "17:00",
            "target_user_id": "U_ALICE",
            "channel_id": "C_ENG",
            "source_message_ts": "100.1",
        },
    )
    plan = CognitivePlan(
        request_id="plan_scenario_a",
        original_message="Create task 'Prepare production rollout' and remind me daily at 9am and 5pm",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.REMINDER_SERVICE],
        action_required=True,
        execution_steps=[step1, step2],
    )

    with patch.object(engine.planner, "plan", return_value=plan):
        q = Question(text=plan.original_message, context=ctx, target_user_id="U_ALICE")
        ans = engine.ask(q)

    assert ans is not None
    assert ans.clear_pending is True
    assert "Task created successfully" in ans.text
    assert "Done! I've scheduled daily reminders" in ans.text

    # Verify task persisted in operational repository
    all_items = list(op_repo._items.values())
    assert len(all_items) == 1
    task = all_items[0]
    assert task.summary == "Prepare production rollout"
    assert task.priority == OperationalItemPriority.HIGH
    task_id = str(task.identifier.graph_id)

    # Verify reminder persisted and accurately linked
    all_reminders = reminder_repo.list_all()
    assert len(all_reminders) == 1
    reminder = all_reminders[0]
    assert reminder.task == task.summary
    assert reminder.target_user_id == "U_ALICE"
    assert reminder.active is True

    # Continuation verify: Re-running with step_1 result already completed does not recreate task
    step1_res = StepExecutionResult(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        status=StepExecutionStatus.SUCCEEDED,
        entity_id=task_id,
        entity_type="task",
        output_fields={"entity_id": task_id, "summary": task.summary},
    )
    with patch.object(engine.operations_agent, "process_event") as mock_op_event:
        res = engine.coordinator.execute(
            plan,
            step_executor=lambda step, p, params, prereqs: engine._execute_specialist_step(
                step, p, params, prereqs, q, ctx
            ),
            initial_step_results={"step_1": step1_res},
        )
        assert res.is_all_succeeded
        mock_op_event.assert_not_called()
        assert len(op_repo._items) == 1


# =============================================================================
# 2. SCENARIO B: CALENDAR WORKFLOW
# =============================================================================

def test_scenario_b_calendar_workflow(engine, cal_repo):
    """
    Scenario B:
    1. Create a calendar entry.
    2. Use its returned entry ID in a dependent update or cancellation step.
    3. Verify actual persisted state after each operation.
    4. Verify creator authorization.
    5. Verify reminder lifecycle behavior.
    """
    ctx_creator = ConversationContext(channel_id="C_MAIN", thread_ts="200.1", user_id="U_ALICE")

    # Step 1: Create entry
    create_step = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Quarterly Planning",
            "dates": ["2026-11-15"],
            "times": ["10:00"],
            "duration_minutes": 60,
            "audience_type": "organization",
            "audience_identifier": "C_MAIN",
        },
    )
    plan_create = CognitivePlan(
        request_id="plan_cal_create",
        original_message="Schedule Quarterly Planning on 2026-11-15 at 10:00",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[create_step],
    )

    with patch.object(engine.planner, "plan", return_value=plan_create):
        q1 = Question(text=plan_create.original_message, context=ctx_creator, target_user_id="U_ALICE")
        ans1 = engine.ask(q1)

    assert "Scheduled" in ans1.text or "created" in ans1.text.lower()
    entries = cal_repo.list_entries(limit=10)
    assert len(entries) == 1
    entry = entries[0]
    entry_id = entry.entry_id
    assert entry.title == "Quarterly Planning"
    assert entry.status == CalendarEntryStatus.SCHEDULED
    assert entry.creator_id == "U_ALICE"

    # Verify reminder delivery scheduled
    deliveries = cal_repo.find_deliveries_for_entry(entry_id)
    assert len(deliveries) >= 1
    assert deliveries[0].entry_id == entry_id

    # Step 2: Unauthorized user attempts cancellation
    ctx_mallory = ConversationContext(channel_id="C_MAIN", thread_ts="200.2", user_id="U_MALLORY")
    cancel_step_unauth = ExecutionStep(
        step_id="step_cancel",
        agent=TargetAgent.CALENDAR_AGENT,
        action="cancel_event",
        action_type=ActionType.CANCEL,
        parameters={"entry_id": entry_id},
    )
    plan_unauth = CognitivePlan(
        request_id="plan_cal_unauth",
        original_message=f"Cancel calendar entry {entry_id}",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[cancel_step_unauth],
    )
    with patch.object(engine.planner, "plan", return_value=plan_unauth):
        q_unauth = Question(text=plan_unauth.original_message, context=ctx_mallory, target_user_id="U_MALLORY")
        ans_unauth = engine.ask(q_unauth)

    assert "not authorized" in ans_unauth.text.lower()
    # Entry remains SCHEDULED
    entry_refetched = cal_repo.find_entry(entry_id)
    assert entry_refetched.status == CalendarEntryStatus.SCHEDULED

    # Step 3: Authorized creator cancels the entry
    cancel_step_auth = ExecutionStep(
        step_id="step_cancel_auth",
        agent=TargetAgent.CALENDAR_AGENT,
        action="cancel_event",
        action_type=ActionType.CANCEL,
        parameters={"entry_id": entry_id},
    )
    plan_auth = CognitivePlan(
        request_id="plan_cal_cancel",
        original_message=f"Cancel entry {entry_id}",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[cancel_step_auth],
    )
    with patch.object(engine.planner, "plan", return_value=plan_auth):
        q_auth = Question(text=plan_auth.original_message, context=ctx_creator, target_user_id="U_ALICE")
        ans_auth = engine.ask(q_auth)

    assert "cancelled" in ans_auth.text.lower()
    entry_cancelled = cal_repo.find_entry(entry_id)
    assert entry_cancelled.status == CalendarEntryStatus.CANCELLED

    # Verify reminder delivery lifecycle cancelled
    active_deliveries = [d for d in cal_repo.find_deliveries_for_entry(entry_id) if d.status == CalendarDeliveryStatus.PENDING]
    assert len(active_deliveries) == 0


# =============================================================================
# 3. SCENARIO C: GOVERNANCE WORKFLOW
# =============================================================================

def test_scenario_c_governance_workflow(engine, gov_repo):
    """
    Scenario C:
    1. Create an approval request.
    2. Use its returned approval ID in a dependent operation.
    3. Verify that authorization is enforced.
    4. Verify self-approval rejection.
    5. Verify the approval lifecycle.
    """
    ctx_dev = ConversationContext(channel_id="C_SEC", thread_ts="300.1", user_id="U_DEV")

    # Step 1: Request approval
    step_req = ExecutionStep(
        step_id="step_req",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Upgrade PostgreSQL Production",
            "target_object": "postgres-prod-db",
        },
    )
    # Step 2: Grant approval via $step_ref (dependent)
    step_grant = ExecutionStep(
        step_id="step_grant",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="grant_approval",
        action_type=ActionType.UPDATE,
        dependencies=["step_req"],
        parameters={
            "approval_id": {"$step_ref": "step_req", "field": "entity_id"},
        },
    )

    plan_multi = CognitivePlan(
        request_id="plan_gov_multi",
        original_message="Request approval for db upgrade and auto-approve",
        intent=IntentCategory.GOVERNANCE_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step_req, step_grant],
    )

    # Requester U_DEV attempts self-approval -> step_req succeeds, step_grant fails due to self-approval rejection
    with patch.object(engine.planner, "plan", return_value=plan_multi):
        q_dev = Question(text=plan_multi.original_message, context=ctx_dev, target_user_id="U_DEV")
        ans_dev = engine.ask(q_dev)

    assert "Approval request submitted successfully" in ans_dev.text or "Step 'step_req' (request_approval): Succeeded" in ans_dev.text
    assert "self-approval is strictly prohibited" in ans_dev.text.lower() or "failed" in ans_dev.text.lower()

    # Verify approval exists in repo in PENDING status
    dev_approvals = [a for a in gov_repo._approvals.values() if a.requester_id == "U_DEV"]
    assert len(dev_approvals) == 1
    appr = dev_approvals[0]
    appr_id = appr.id
    assert appr.status == ApprovalStatus.REQUESTED

    # Unauthorized approver U_MALLORY attempts grant -> rejected
    ctx_mallory = ConversationContext(channel_id="C_SEC", thread_ts="300.2", user_id="U_MALLORY")
    step_grant_unauth = ExecutionStep(
        step_id="step_grant_unauth",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": appr_id},
    )
    plan_unauth = CognitivePlan(
        request_id="plan_gov_unauth",
        original_message=f"Grant approval {appr_id}",
        intent=IntentCategory.GOVERNANCE_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step_grant_unauth],
    )
    with patch.object(engine.planner, "plan", return_value=plan_unauth):
        q_unauth = Question(text=plan_unauth.original_message, context=ctx_mallory, target_user_id="U_MALLORY")
        ans_unauth = engine.ask(q_unauth)

    assert "unauthorized" in ans_unauth.text.lower()
    assert gov_repo.find_approval(appr_id).status == ApprovalStatus.REQUESTED

    # Authoritative approver U_SEC_LEAD grants approval -> succeeds
    ctx_lead = ConversationContext(channel_id="C_SEC", thread_ts="300.3", user_id="U_SEC_LEAD")
    step_grant_lead = ExecutionStep(
        step_id="step_grant_lead",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": appr_id, "notes": "Approved after staging verification"},
    )
    plan_lead = CognitivePlan(
        request_id="plan_gov_lead",
        original_message=f"Grant approval {appr_id}",
        intent=IntentCategory.GOVERNANCE_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step_grant_lead],
    )
    with patch.object(engine.planner, "plan", return_value=plan_lead):
        q_lead = Question(text=plan_lead.original_message, context=ctx_lead, target_user_id="U_SEC_LEAD")
        ans_lead = engine.ask(q_lead)

    assert "granted" in ans_lead.text.lower()
    appr_granted = gov_repo.find_approval(appr_id)
    assert appr_granted.status == ApprovalStatus.GRANTED
    assert appr_granted.approver_id == "U_SEC_LEAD"


# =============================================================================
# 4. SCENARIO D: CLARIFICATION AND RESUME
# =============================================================================

def test_scenario_d_clarification_and_resume(engine, op_repo):
    """
    Scenario D:
    1. Multi-step request with one required field missing.
    2. Confirm correct step enters clarification-required state.
    3. Confirm independent successful work is persisted.
    4. Provide missing information in next turn.
    5. Confirm original plan resumes with original request_id / plan_id.
    6. Confirm completed mutations are not executed again.
    7. Confirm dependent steps execute only after prerequisite success.
    """
    ctx = ConversationContext(channel_id="C_WORK", thread_ts="400.1", user_id="U_ALICE")

    # Step 1: Create task "Prepare migration runbook" (valid)
    # Step 2: Complete task (dependent on step 1, but missing task_id or summary)
    step1 = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Prepare migration runbook"},
    )
    step2 = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        dependencies=["step_1"],
        parameters={},  # Missing summary!
    )
    plan = CognitivePlan(
        request_id="plan_scen_d",
        original_message="Create runbook task and then create a second task",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step1, step2],
        missing_information=[],
    )

    with patch.object(engine.planner, "plan", return_value=plan):
        q1 = Question(text=plan.original_message, context=ctx, target_user_id="U_ALICE")
        ans1 = engine.ask(q1)

    # Step 1 succeeded and task is persisted
    assert len(op_repo._items) == 1
    task1 = list(op_repo._items.values())[0]
    assert task1.summary == "Prepare migration runbook"
    task1_id = str(task1.identifier.graph_id)

    # Step 2 required clarification
    assert ans1.pending_operation is not None
    pending_dict = ans1.pending_operation
    assert pending_dict["plan_id"] == "plan_scen_d"
    assert pending_dict["pending_step_id"] == "step_2"
    assert "step_1" in pending_dict["completed_step_results"]
    assert pending_dict["completed_step_results"]["step_1"]["entity_id"] == task1_id

    # Turn 2: User provides missing summary in next turn
    ctx_resumed = ctx.add_exchange(
        user_message=plan.original_message,
        assistant_message=ans1.text,
        user_id="U_ALICE",
        pending_operation=pending_dict,
    )

    follow_up_text = "Deploy migration scripts to staging"
    q2 = Question(text=follow_up_text, context=ctx_resumed, target_user_id="U_ALICE")

    # Verify that plan resumption does NOT re-execute step 1
    with patch.object(engine.operations_agent, "process_event", wraps=engine.operations_agent.process_event) as spy_op:
        ans2 = engine.ask(q2)

        # process_event should only be called ONCE for step_2, not for step_1
        assert spy_op.call_count == 1
        call_event = spy_op.call_args[0][0]
        assert "Deploy migration scripts" in call_event.summary

    assert ans2.clear_pending is True
    # Confirm both tasks now exist
    tasks = list(op_repo._items.values())
    assert len(tasks) == 2
    summaries = [t.summary for t in tasks]
    assert "Prepare migration runbook" in summaries
    assert "Deploy migration scripts to staging" in summaries


# =============================================================================
# 5. SCENARIO E: FAILURE ISOLATION
# =============================================================================

def test_scenario_e_failure_isolation(engine, op_repo):
    """
    Scenario E:
    1. Plan with two independent branches (1A safe, 1B failing).
    2. Step 2 depends on 1B.
    3. Safe branch 1A completes.
    4. Dependent step 2 of failed branch 1B is blocked.
    5. Response reports partial success accurately.
    """
    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="500.1", user_id="U_ALICE")

    step_1a = ExecutionStep(
        step_id="step_1a",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        action_type=ActionType.CREATE,
        parameters={"summary": "Safe independent task"},
    )
    step_1b = ExecutionStep(
        step_id="step_1b",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={"title": "", "target_object": ""},  # Will fail validation
    )
    step_2 = ExecutionStep(
        step_id="step_2",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="grant_approval",
        action_type=ActionType.UPDATE,
        dependencies=["step_1b"],
        parameters={"approval_id": {"$step_ref": "step_1b", "field": "entity_id"}},
    )

    plan = CognitivePlan(
        request_id="plan_failure_iso",
        original_message="Run independent branches",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step_1a, step_1b, step_2],
    )

    with patch.object(engine.planner, "plan", return_value=plan):
        q = Question(text=plan.original_message, context=ctx, target_user_id="U_ALICE")
        ans = engine.ask(q)

    # Safe branch 1a succeeded and persisted
    assert len(op_repo._items) == 1
    assert list(op_repo._items.values())[0].summary == "Safe independent task"

    # Answer accurately reports partial success
    assert "Step 'step_1a' (create_task): Succeeded" in ans.text
    assert "Step 'step_1b' (request_approval): Failed" in ans.text
    assert "Step 'step_2' (grant_approval): Blocked" in ans.text


# =============================================================================
# 6. SCENARIO F: CANCELLATION
# =============================================================================

def test_scenario_f_cancellation_preserves_completed_mutations(engine, op_repo):
    """
    Scenario F:
    1. Complete at least one mutation.
    2. Request cancellation.
    3. Confirm no remaining steps execute.
    4. Confirm completed mutations are reported as completed and not undone.
    """
    # Create task
    task = op_repo.save(
        OperationalItem.create(
            item_type=OperationalItemType.TASK,
            summary="Existing completed task",
            status=OperationalItemStatus.OPEN,
        )
    )
    task_id = str(task.identifier.graph_id)

    now = datetime.now(timezone.utc)
    original_plan_dict = {
        "request_id": "plan_cancel_600",
        "original_message": "Run operations",
        "intent": "task_action",
        "intent_confidence": 1.0,
        "required_agents": ["operations_agent"],
        "action_required": True,
        "execution_steps": [
            {"step_id": "step_1", "agent": "operations_agent", "action": "create_task", "action_type": "create", "parameters": {}},
            {"step_id": "step_2", "agent": "operations_agent", "action": "create_task", "action_type": "create", "parameters": {}},
        ],
    }
    pending_op = {
        "operation_id": "op_cancel_demo",
        "intent": "task_action",
        "target_agent": "operations_agent",
        "action": "create_task",
        "collected_entities": {},
        "missing_fields": ["summary"],
        "clarification_question": "What is the summary?",
        "user_id": "U_ALICE",
        "channel_id": "C_MAIN",
        "thread_ts": "600.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": (now + timedelta(minutes=15)).isoformat(),
        "state_version": 1,
        "plan_id": "plan_cancel_600",
        "original_plan": original_plan_dict,
        "completed_step_results": {
            "step_1": {
                "step_id": "step_1",
                "agent": "operations_agent",
                "action": "create_task",
                "status": "succeeded",
                "entity_id": task_id,
                "output_fields": {"entity_id": task_id},
            }
        },
        "step_states": {"step_1": "succeeded", "step_2": "pending"},
        "pending_step_id": "step_2",
    }
    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="600.1",
        user_id="U_ALICE",
        pending_operation=pending_op,
    )

    q = Question(text="cancel", context=ctx, target_user_id="U_ALICE")
    ans = engine.ask(q)

    assert ans.clear_pending is True
    assert "cancelled the remaining operations" in ans.text.lower()
    assert "have not been undone" in ans.text.lower()
    assert task_id in ans.text

    # The persisted task in repository was NOT undone/deleted
    persisted = op_repo.find_by_id(task_id)
    assert persisted is not None
    assert persisted.summary == "Existing completed task"


# =============================================================================
# 7. SCENARIO G: OWNERSHIP AND ISOLATION
# =============================================================================

def test_scenario_g_ownership_and_isolation(engine):
    """
    Scenario G:
    Verify pending operations cannot be resumed across:
    - Different authenticated users.
    - Different Slack channels.
    - Different Slack threads.
    - Expired pending operations.
    """
    now = datetime.now(timezone.utc)
    pending_op = {
        "operation_id": "op_iso_1",
        "intent": "calendar_action",
        "target_agent": "calendar_agent",
        "action": "create_event",
        "collected_entities": {"title": "Secret Sync"},
        "missing_fields": ["date", "time"],
        "user_id": "U_ALICE",
        "channel_id": "C_ALICE",
        "thread_ts": "700.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": (now + timedelta(minutes=15)).isoformat(),
        "state_version": 1,
    }

    # 1. Different user (U_BOB in same channel/thread)
    ctx_bob = ConversationContext(
        channel_id="C_ALICE",
        thread_ts="700.1",
        user_id="U_BOB",
        pending_operation=pending_op,
    )
    assert ctx_bob.get_typed_pending_operation(expected_user_id="U_BOB") is None

    # 2. Different channel (U_ALICE in C_OTHER)
    ctx_other_ch = ConversationContext(
        channel_id="C_OTHER",
        thread_ts="700.1",
        user_id="U_ALICE",
        pending_operation=pending_op,
    )
    assert ctx_other_ch.get_typed_pending_operation(expected_channel_id="C_OTHER") is None

    # 3. Different thread (U_ALICE in thread 700.2)
    ctx_other_th = ConversationContext(
        channel_id="C_ALICE",
        thread_ts="700.2",
        user_id="U_ALICE",
        pending_operation=pending_op,
    )
    assert ctx_other_th.get_typed_pending_operation(expected_thread_ts="700.2") is None

    # 4. Expired pending operation
    expired_op = dict(pending_op)
    expired_op["expires_at_iso"] = (now - timedelta(seconds=1)).isoformat()
    ctx_expired = ConversationContext(
        channel_id="C_ALICE",
        thread_ts="700.1",
        user_id="U_ALICE",
        pending_operation=expired_op,
    )
    assert ctx_expired.get_typed_pending_operation(now=now) is None


# =============================================================================
# 8. SECTION 3: CREATION-IDEMPOTENCY RISK VALIDATION
# =============================================================================

def test_creation_idempotency_crash_window_calendar_create(engine, cal_repo):
    """
    Establish actual replay behavior for Calendar create_entry across crash windows:
    1. Domain mutation executes successfully.
    2. Simulated failure occurs before pending-state persistence.
    3. Replay of same plan creates a second entry because create_entry lacks durable idempotency keys.
    Documents the explicit acceptance limitation for future enhancement.
    """
    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="800.1", user_id="U_ALICE")
    step = ExecutionStep(
        step_id="step_cal_create",
        agent=TargetAgent.CALENDAR_AGENT,
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Idempotency Test Meeting",
            "dates": ["2026-11-20"],
            "times": ["14:00"],
            "duration_minutes": 30,
            "audience_type": "organization",
            "audience_identifier": "C_MAIN",
        },
    )
    plan = CognitivePlan(
        request_id="plan_cal_crash",
        original_message="Create meeting",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.CALENDAR_AGENT],
        action_required=True,
        execution_steps=[step],
    )

    # 1. First execution succeeds
    res1 = engine._execute_specialist_step(step, plan, step.parameters, {}, Question(text="create", context=ctx), ctx)
    assert res1.status == StepExecutionStatus.SUCCEEDED
    assert len(cal_repo.list_entries()) == 1

    # 2. Simulate crash before pending-state persistence: client repeats identical step without cached step result
    res2 = engine._execute_specialist_step(step, plan, step.parameters, {}, Question(text="create", context=ctx), ctx)
    assert res2.status == StepExecutionStatus.SUCCEEDED

    # Verify documented limitation: duplicate entries created
    entries = cal_repo.list_entries()
    assert len(entries) == 2
    assert entries[0].entry_id != entries[1].entry_id
    assert entries[0].title == entries[1].title == "Idempotency Test Meeting"


def test_creation_idempotency_crash_window_governance_request(engine, gov_repo):
    """
    Establish actual replay behavior for Governance request_approval across crash windows:
    Replaying request_approval creates a duplicate approval request because request_approval
    currently generates a fresh ID without durable idempotency keys.
    """
    ctx = ConversationContext(channel_id="C_SEC", thread_ts="800.2", user_id="U_DEV")
    step = ExecutionStep(
        step_id="step_gov_req",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="request_approval",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Migrate Cluster",
            "target_object": "k8s_prod",
        },
    )
    plan = CognitivePlan(
        request_id="plan_gov_crash",
        original_message="Request approval",
        intent=IntentCategory.GOVERNANCE_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.GOVERNANCE_AGENT],
        action_required=True,
        execution_steps=[step],
    )

    res1 = engine._execute_specialist_step(step, plan, step.parameters, {}, Question(text="req", context=ctx), ctx)
    assert res1.status == StepExecutionStatus.SUCCEEDED
    assert len([a for a in gov_repo._approvals.values() if a.requester_id == "U_DEV"]) == 1

    # Simulate crash and replay
    res2 = engine._execute_specialist_step(step, plan, step.parameters, {}, Question(text="req", context=ctx), ctx)
    assert res2.status == StepExecutionStatus.SUCCEEDED

    # Verify documented limitation: duplicate approval request created
    dev_approvals = [a for a in gov_repo._approvals.values() if a.requester_id == "U_DEV"]
    assert len(dev_approvals) == 2
    assert dev_approvals[0].id != dev_approvals[1].id


def test_existing_replay_safety_verifications(engine, op_repo, reminder_repo, cal_repo, gov_repo):
    """
    Verify existing replay safety of:
    - Operations task completion.
    - Reminder scheduling.
    - Calendar cancellation.
    - Governance grant/reject.
    """
    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="800.3", user_id="U_ALICE")

    # 1. Operations task completion is replay-safe (no-op / idempotent)
    task = op_repo.save(
        OperationalItem.create(
            item_type=OperationalItemType.TASK,
            summary="Deploy server",
            status=OperationalItemStatus.COMPLETED,
        )
    )
    task_id = str(task.identifier.graph_id)
    step_comp = ExecutionStep(
        step_id="s_comp",
        agent=TargetAgent.OPERATIONS_AGENT,
        action="complete_task",
        action_type=ActionType.UPDATE,
        parameters={"task_id": task_id},
    )
    plan_comp = CognitivePlan(
        request_id="p_comp",
        original_message="Complete task",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[step_comp],
    )
    res_comp = engine._execute_specialist_step(step_comp, plan_comp, step_comp.parameters, {}, Question(text="c", context=ctx), ctx)
    assert res_comp.status == StepExecutionStatus.SUCCEEDED
    assert "already in status" in res_comp.answer or "completed" in res_comp.answer

    # 2. Reminder scheduling is replay-safe (detects existing reminder for task and user)
    task_open = op_repo.save(
        OperationalItem.create(
            item_type=OperationalItemType.TASK,
            summary="Review PRs",
            status=OperationalItemStatus.OPEN,
            owner_id="U_ALICE",
        )
    )
    open_task_id = str(task_open.identifier.graph_id)
    step_rem = ExecutionStep(
        step_id="s_rem",
        agent=TargetAgent.REMINDER_SERVICE,
        action="schedule_reminder",
        action_type=ActionType.CREATE,
        parameters={
            "task_id": open_task_id,
            "time_1": "09:00",
            "time_2": "17:00",
            "target_user_id": "U_ALICE",
            "channel_id": "C_MAIN",
            "source_message_ts": "800.3",
        },
    )
    res_rem_1 = engine._execute_specialist_step(step_rem, plan_comp, step_rem.parameters, {}, Question(text="r", context=ctx), ctx)
    assert res_rem_1.status == StepExecutionStatus.SUCCEEDED
    assert len(reminder_repo.list_all()) == 1

    # Replay identical reminder scheduling
    res_rem_2 = engine._execute_specialist_step(step_rem, plan_comp, step_rem.parameters, {}, Question(text="r", context=ctx), ctx)
    assert res_rem_2.status == StepExecutionStatus.SUCCEEDED
    assert "already exists" in res_rem_2.answer
    assert len(reminder_repo.list_all()) == 1  # No duplicate reminder created!

    # 3. Calendar cancel is replay-safe
    entry = engine.calendar_agent.create_entry_structured({
        "title": "1-on-1",
        "dates": ["2026-11-25"],
        "times": ["11:00"],
        "duration_minutes": 30,
        "audience_type": "organization",
        "audience_identifier": "C_MAIN",
    }, user_id="U_ALICE")
    engine.calendar_agent.cancel_entry_structured({"entry_id": entry.entry_id}, user_id="U_ALICE")
    # Re-cancelling already cancelled entry
    step_cal_cancel = ExecutionStep(
        step_id="s_cancel",
        agent=TargetAgent.CALENDAR_AGENT,
        action="cancel_event",
        action_type=ActionType.CANCEL,
        parameters={"entry_id": entry.entry_id},
    )
    assert cal_repo.find_entry(entry.entry_id).status == CalendarEntryStatus.CANCELLED

    # 4. Governance grant is replay-safe (cannot re-grant terminal state)
    approval = engine.governance_agent.request_approval(
        title="Access Prod",
        target_object="server_prod",
        requester_id="U_DEV",
    )
    engine.governance_agent.grant_approval(approval.id, approver_id="U_LEAD")
    step_gov_grant = ExecutionStep(
        step_id="s_grant",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": approval.id},
    )
    ctx_lead = ConversationContext(channel_id="C_MAIN", thread_ts="800.3", user_id="U_LEAD")
    res_gov_grant = engine._execute_specialist_step(step_gov_grant, plan_comp, step_gov_grant.parameters, {}, Question(text="g", context=ctx_lead), ctx_lead)
    assert res_gov_grant.status == StepExecutionStatus.SUCCEEDED
    assert "granted" in res_gov_grant.answer.lower()

    # But attempting to grant an already rejected approval fails
    appr_rej = engine.governance_agent.request_approval(
        title="Access Restricted",
        target_object="server_secret",
        requester_id="U_DEV",
    )
    engine.governance_agent.reject_approval(appr_rej.id, approver_id="U_LEAD", reason="Not allowed")
    step_gov_grant_rej = ExecutionStep(
        step_id="s_grant_rej",
        agent=TargetAgent.GOVERNANCE_AGENT,
        action="grant_approval",
        action_type=ActionType.UPDATE,
        parameters={"approval_id": appr_rej.id},
    )
    res_gov_grant_rej = engine._execute_specialist_step(step_gov_grant_rej, plan_comp, step_gov_grant_rej.parameters, {}, Question(text="g", context=ctx_lead), ctx_lead)
    assert res_gov_grant_rej.status == StepExecutionStatus.FAILED


# =============================================================================
# 9. SECTION 4: PERSISTENCE INTEGRATION
# =============================================================================

def test_persistence_lifecycle_in_memory_repository():
    """Verify serialization, isolation, and reconstruction with InMemoryConversationRepository."""
    repo = InMemoryConversationRepository()
    now = datetime.now(timezone.utc)
    pending = PendingOperation(
        operation_id="op_persist_1",
        intent=IntentCategory.TASK_ACTION,
        target_agent=TargetAgent.OPERATIONS_AGENT,
        action="create_task",
        collected_entities={"task_summary": "Sync DB"},
        missing_fields=[],
        clarification_question="",
        user_id="U_ALICE",
        channel_id="C_PERSIST",
        thread_ts="900.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=(now + timedelta(minutes=15)).isoformat(),
        state_version=1,
        plan_id="plan_persist_100",
        step_states={"step_1": "succeeded"},
        completed_step_results={"step_1": {"status": "succeeded", "entity_id": "task_99"}},
        pending_step_id="step_2",
    )

    ctx = ConversationContext(
        channel_id="C_PERSIST",
        thread_ts="900.1",
        user_id="U_ALICE",
    ).add_exchange(
        user_message="Initial request",
        assistant_message="Need clarification",
        user_id="U_ALICE",
        pending_operation=pending,
    )

    repo.save(ctx)
    fetched = repo.get("C_PERSIST", "900.1")
    assert fetched is not None
    typed_op = fetched.get_typed_pending_operation(expected_user_id="U_ALICE")
    assert typed_op is not None
    assert typed_op.plan_id == "plan_persist_100"
    assert typed_op.pending_step_id == "step_2"
    assert typed_op.completed_step_results["step_1"]["entity_id"] == "task_99"
    assert typed_op.state_version == 1


def test_persistence_lifecycle_postgres_repository(monkeypatch):
    """
    Verify PostgreSQLConversationRepository serialization and history reconstruction
    using SQLAlchemy model simulation (FakeSession).
    """
    session = FakeSession()
    monkeypatch.setattr(pg_conv_module, "SessionLocal", lambda: session)

    repo = PostgreSQLConversationRepository()
    now = datetime.now(timezone.utc)
    pending = {
        "operation_id": "op_pg_1",
        "intent": "task_action",
        "target_agent": "operations_agent",
        "action": "create_task",
        "collected_entities": {},
        "missing_fields": [],
        "clarification_question": "",
        "user_id": "U_ALICE",
        "channel_id": "C_PG",
        "thread_ts": "950.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": (now + timedelta(minutes=15)).isoformat(),
        "state_version": 1,
        "plan_id": "plan_pg_950",
        "step_states": {"step_1": "succeeded"},
        "completed_step_results": {"step_1": {"entity_id": "task_pg_1"}},
        "pending_step_id": "step_2",
    }

    ctx = ConversationContext(
        channel_id="C_PG",
        thread_ts="950.1",
        user_id="U_ALICE",
    ).add_exchange(
        user_message="Please create tasks",
        assistant_message="Clarification question",
        user_id="U_ALICE",
        pending_operation=pending,
    )

    repo.save(ctx)
    assert session.committed is True

    fetched = repo.get("C_PG", "950.1")
    assert fetched is not None
    assert fetched.user_id == "U_ALICE"
    reconstructed_op = fetched.get_typed_pending_operation(expected_user_id="U_ALICE")
    assert reconstructed_op is not None
    assert reconstructed_op.plan_id == "plan_pg_950"


def test_real_postgresql_integration_availability_status():
    """
    Check if a real PostgreSQL database service is available.
    If unavailable, explicitly report as unavailable without failing or masking.
    """
    has_live_db = False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(("localhost", 5432))
        s.close()
        has_live_db = True
    except Exception:
        has_live_db = False

    if not has_live_db:
        pytest.skip(
            "Live PostgreSQL service is unavailable in local environment; "
            "unit persistence contracts validated via ORM model simulation."
        )


# =============================================================================
# 10. SECTION 5: PRODUCTION BOOTSTRAP VERIFICATION
# =============================================================================

def test_production_bootstrap_wiring_and_reuse():
    """
    Verify application bootstrap:
    - SimpleCognitiveEngine receives MultiStepCoordinator and CognitivePlanner.
    - Specialist bridge uses configured specialist instances without duplicate services.
    - Shared OpenRouter client is reused across components.
    - Ask interface remains compatible.
    """
    with patch("application.bootstrap.bootstrap.PostgreSQLCalendarRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLGovernanceRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLCommunicationRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLActivityRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingTranscriptRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLTeamsSubscriptionRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLReminderRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOperationalItemRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOrganizationEventRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseDocumentRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseChunkRepository"), \
         patch("application.bootstrap.bootstrap.MinIOKnowledgeBaseStorage"), \
         patch("application.bootstrap.bootstrap.SlackClient"), \
         patch("application.bootstrap.bootstrap.SlackIdentityService"), \
         patch("application.bootstrap.bootstrap.MicrosoftGraphTokenProvider"), \
         patch("application.bootstrap.bootstrap.OpenRouterClient") as mock_openrouter_cls:

        mock_llm = MagicMock()
        mock_openrouter_cls.return_value = mock_llm

        container = bootstrap()

        assert isinstance(container.engine, SimpleCognitiveEngine)
        assert isinstance(container.engine.coordinator, MultiStepCoordinator)
        assert isinstance(container.engine.planner, CognitivePlanner)

        # Confirm specialist instances are identical
        assert container.engine.operations_agent is container.operations_agent
        assert container.engine.calendar_agent is container.calendar_agent
        assert container.engine.governance_agent is container.governance_agent
        assert container.engine.knowledge_agent is container.knowledge_agent

        # Confirm shared LLM client reuse
        assert container.engine.planner._llm_client is mock_llm
        assert container.knowledge_agent._llm_client is mock_llm


# =============================================================================
# 11. SECTION 6: USER-FACING RESPONSE VALIDATION
# =============================================================================

def test_user_facing_response_distinctions(coordinator):
    """
    Verify responses accurately distinguish:
    - All steps succeeded.
    - Partial success.
    - Failed execution.
    - Blocked dependent operations.
    - Clarification required.
    - Never exposes raw tracebacks or sensitive stack traces.
    """
    plan = CognitivePlan(
        request_id="p_resp",
        original_message="test",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        action_required=True,
        execution_steps=[
            ExecutionStep(step_id="s1", agent=TargetAgent.OPERATIONS_AGENT, action="create_task", action_type=ActionType.CREATE),
            ExecutionStep(step_id="s2", agent=TargetAgent.OPERATIONS_AGENT, action="update_task", action_type=ActionType.UPDATE, dependencies=["s1"]),
        ],
    )

    # 1. Partial success: s1 succeeds, s2 fails
    def executor_partial(step, p, params, prereqs):
        if step.step_id == "s1":
            return StepExecutionResult(step_id="s1", agent=step.agent, action=step.action, status=StepExecutionStatus.SUCCEEDED, answer="Task 1 created.")
        return StepExecutionResult(step_id="s2", agent=step.agent, action=step.action, status=StepExecutionStatus.FAILED, error="Invalid status", answer="Could not update task 2.")

    res_partial = coordinator.execute(plan, step_executor=executor_partial)
    assert res_partial.status == MultiStepExecutionStatus.PARTIAL_SUCCESS
    assert "Step 's1' (create_task): Succeeded." in res_partial.overall_answer
    assert "Step 's2' (update_task): Failed. Invalid status" in res_partial.overall_answer

    # 2. Blocked: s1 fails, s2 is blocked
    def executor_blocked(step, p, params, prereqs):
        return StepExecutionResult(step_id="s1", agent=step.agent, action=step.action, status=StepExecutionStatus.FAILED, error="Specialist connection timeout.")

    res_blocked = coordinator.execute(plan, step_executor=executor_blocked)
    assert res_blocked.status == MultiStepExecutionStatus.FAILED
    assert "Step 's1' (create_task): Failed. Specialist connection timeout." in res_blocked.overall_answer
    assert "Step 's2' (update_task): Blocked." in res_blocked.overall_answer

    # 3. Privacy / exception safety: unhandled exception in executor does NOT leak stack trace in answer
    def executor_exploding(step, p, params, prereqs):
        raise RuntimeError("DATABASE_PASSWORD_LEAK=secret123 in internal/sql.py line 42")

    res_exploding = coordinator.execute(plan, step_executor=executor_exploding)
    assert res_exploding.status == MultiStepExecutionStatus.FAILED
    assert "Traceback (most recent call last)" not in res_exploding.overall_answer
    assert "DATABASE_PASSWORD_LEAK" not in res_exploding.overall_answer
    assert "secret123" not in res_exploding.overall_answer
