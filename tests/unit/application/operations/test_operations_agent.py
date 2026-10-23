"""
Unit tests for the Operations Agent specialist.
"""

from datetime import datetime, timezone, timedelta
import pytest

from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemType,
    OperationalItemStatus,
    OperationalItemPriority,
    InMemoryOperationalItemRepository,
    InvalidLifecycleTransitionError,
    OperationalItemNotFoundError,
    UnsupportedOperationalEventError,
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
from application.operations import (
    OperationsAgent,
    OperationalItemService,
)


def _make_event(
    event_type: OrganizationEventType,
    summary: str,
    *,
    metadata: dict | None = None,
    evidence: list[str] | None = None,
    confidence: float = 0.9,
) -> OrganizationEvent:
    meta = metadata or {}
    obs_type = ObservationType.TASK
    if event_type == OrganizationEventType.DECISION_MADE:
        obs_type = ObservationType.DECISION
    elif event_type == OrganizationEventType.RISK_IDENTIFIED:
        obs_type = ObservationType.RISK
    elif event_type == OrganizationEventType.QUESTION_ASKED:
        obs_type = ObservationType.QUESTION

    obs = Observation(
        observation_type=obs_type,
        summary=summary,
        evidence=evidence or ["slack msg ref 123"],
        confidence=confidence,
        metadata=meta,
    )
    return OrganizationEvent(
        event_type=event_type,
        observations=[obs],
        summary=summary,
        confidence=confidence,
    )


class FakeReminderService:
    def __init__(self):
        self.created_reminders = []

    def create(self, **kwargs):
        self.created_reminders.append(kwargs)
        return kwargs


@pytest.fixture
def repo():
    return InMemoryOperationalItemRepository()


@pytest.fixture
def service(repo):
    return OperationalItemService(repo)


@pytest.fixture
def reminder_service():
    return FakeReminderService()


@pytest.fixture
def agent(repo, service, reminder_service):
    return OperationsAgent(
        repository=repo,
        operational_item_service=service,
        reminder_service=reminder_service,
    )


# -----------------------------------------------------------------------------
# A & B: TASK_CREATED and IDEMPOTENCY
# -----------------------------------------------------------------------------

def test_task_created_creates_task(agent, repo):
    event = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Deploy the payment microservice",
        metadata={
            "assignee": "alice",
            "assignee_name": "Alice Smith",
            "priority": "high",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        },
    )

    result = agent.process_event(
        event,
        source_type="slack",
        source_event_id="evt-100",
        correlation_id="corr-1",
    )

    assert result.operation == "created"
    assert result.status == OperationalItemStatus.OPEN
    assert result.idempotent is False
    assert result.affected_item_id is not None
    assert result.item is not None
    assert result.item.summary == "Deploy the payment microservice"
    assert result.item.owner_id == "alice"
    assert result.item.owner_name == "Alice Smith"
    assert result.item.priority == OperationalItemPriority.HIGH
    assert result.item.source_event_id == "evt-100"

    # Verify repository state
    saved = repo.find_by_id(result.affected_item_id)
    assert saved is not None
    assert saved.summary == "Deploy the payment microservice"


def test_task_created_replay_is_idempotent(agent, repo):
    event = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Deploy the payment microservice",
        metadata={"assignee": "alice"},
    )

    res1 = agent.process_event(
        event,
        source_type="slack",
        source_event_id="evt-100",
        correlation_id="corr-1",
    )
    assert res1.operation == "created"
    assert res1.idempotent is False

    # Process identical event again
    res2 = agent.process_event(
        event,
        source_type="slack",
        source_event_id="evt-100",
        correlation_id="corr-1",
    )
    assert res2.operation == "no_op"
    assert res2.idempotent is True
    assert res2.affected_item_id == res1.affected_item_id

    # Verify exactly one item in repository
    all_open = repo.find_open(item_type=OperationalItemType.TASK)
    assert len(all_open) == 1


# -----------------------------------------------------------------------------
# C: TASK_UPDATED
# -----------------------------------------------------------------------------

def test_task_updated_updates_existing_task(agent, repo):
    create_evt = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Prepare quarterly roadmap",
        metadata={"assignee": "bob", "priority": "medium"},
    )
    agent.process_event(
        create_evt,
        source_type="slack",
        source_event_id="evt-200",
        correlation_id="corr-200",
    )

    update_evt = _make_event(
        OrganizationEventType.TASK_UPDATED,
        "Prepare Q4 executive roadmap",
        metadata={
            "assignee": "charlie",
            "assignee_name": "Charlie Chaplin",
            "priority": "critical",
            "status": "in_progress",
        },
    )
    res = agent.process_event(
        update_evt,
        source_type="slack",
        source_event_id="evt-201",
        correlation_id="corr-200",
    )

    assert res.operation == "updated"
    assert res.status == OperationalItemStatus.IN_PROGRESS
    assert res.item.summary == "Prepare Q4 executive roadmap"
    assert res.item.owner_id == "charlie"
    assert res.item.priority == OperationalItemPriority.CRITICAL


# -----------------------------------------------------------------------------
# D & E: TASK_COMPLETED and IDEMPOTENCY
# -----------------------------------------------------------------------------

def test_task_completed_completes_existing_task(agent, repo):
    create_evt = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Submit security audit response",
    )
    res_create = agent.process_event(
        create_evt,
        source_type="slack",
        source_event_id="evt-300",
        correlation_id="corr-300",
    )

    comp_evt = _make_event(
        OrganizationEventType.TASK_COMPLETED,
        "Submit security audit response",
    )
    res_comp = agent.process_event(
        comp_evt,
        source_type="slack",
        source_event_id="evt-301",
        correlation_id="corr-300",
    )

    assert res_comp.operation == "completed"
    assert res_comp.status == OperationalItemStatus.COMPLETED
    assert res_comp.idempotent is False
    assert res_comp.affected_item_id == res_create.affected_item_id

    # Verify no longer in open items
    assert len(repo.find_open(item_type=OperationalItemType.TASK)) == 0


def test_task_completed_replay_is_idempotent(agent, repo):
    create_evt = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Configure CI runner",
    )
    agent.process_event(
        create_evt,
        source_type="slack",
        source_event_id="evt-400",
        correlation_id="corr-400",
    )

    comp_evt = _make_event(
        OrganizationEventType.TASK_COMPLETED,
        "Configure CI runner",
    )
    res1 = agent.process_event(
        comp_evt,
        source_type="slack",
        source_event_id="evt-401",
        correlation_id="corr-400",
    )
    assert res1.operation == "completed"
    assert res1.idempotent is False

    # Second completion replay
    res2 = agent.process_event(
        comp_evt,
        source_type="slack",
        source_event_id="evt-402",
        correlation_id="corr-400",
    )
    assert res2.operation == "no_op"
    assert res2.idempotent is True
    assert res2.status == OperationalItemStatus.COMPLETED


# -----------------------------------------------------------------------------
# F & G: DECISION_MADE and REPLAY
# -----------------------------------------------------------------------------

def test_decision_made_creates_decision(agent, repo):
    evt = _make_event(
        OrganizationEventType.DECISION_MADE,
        "Adopt PostgreSQL for operational item storage",
        metadata={"assignee": "tech-lead", "approved": True},
    )

    res = agent.process_event(
        evt,
        source_type="meeting",
        source_event_id="meet-10",
        correlation_id="corr-dec-1",
    )

    assert res.operation == "created"
    assert res.status == OperationalItemStatus.ACCEPTED
    assert res.item.item_type == OperationalItemType.DECISION
    assert res.item.owner_id == "tech-lead"

    # Verify persisted in repository
    saved = repo.find_by_id(res.affected_item_id)
    assert saved is not None
    assert saved.summary == "Adopt PostgreSQL for operational item storage"
    assert saved.status == OperationalItemStatus.ACCEPTED

    # Create an open decision and verify get_open_decisions
    evt_open = _make_event(
        OrganizationEventType.DECISION_MADE,
        "Evaluate vector database options",
    )
    res_open = agent.process_event(
        evt_open,
        source_type="meeting",
        source_event_id="meet-11",
        correlation_id="corr-dec-open",
    )
    assert res_open.status == OperationalItemStatus.OPEN

    open_decisions = agent.get_open_decisions()
    assert len(open_decisions) == 1
    assert open_decisions[0].summary == "Evaluate vector database options"


def test_decision_replay_does_not_duplicate(agent, repo):
    evt = _make_event(
        OrganizationEventType.DECISION_MADE,
        "Use Redis for session caching",
    )

    res1 = agent.process_event(
        evt,
        source_type="meeting",
        source_event_id="meet-20",
        correlation_id="corr-dec-2",
    )
    assert res1.operation == "created"

    res2 = agent.process_event(
        evt,
        source_type="meeting",
        source_event_id="meet-20",
        correlation_id="corr-dec-2",
    )
    assert res2.operation == "no_op"
    assert res2.idempotent is True

    assert len(repo.find_open(item_type=OperationalItemType.DECISION)) == 1


def test_decision_superseded_transition(agent, repo):
    dec1_evt = _make_event(
        OrganizationEventType.DECISION_MADE,
        "Use AWS DynamoDB for events",
    )
    res1 = agent.process_event(
        dec1_evt,
        source_type="slack",
        source_event_id="dec-orig",
        correlation_id="dec-arch-choice",
    )

    dec2_evt = _make_event(
        OrganizationEventType.DECISION_MADE,
        "Switch to PostgreSQL for events",
        metadata={"action": "supersede"},
    )
    res2 = agent.process_event(
        dec2_evt,
        source_type="slack",
        source_event_id="dec-new",
        correlation_id="dec-arch-choice",
    )

    # dec1 should be superseded
    old_dec = repo.find_by_id(res1.affected_item_id)
    assert old_dec.status == OperationalItemStatus.SUPERSEDED
    assert res2.item.summary == "Switch to PostgreSQL for events"


# -----------------------------------------------------------------------------
# H & I & J: RISK_IDENTIFIED, REPLAY & LIFECYCLE
# -----------------------------------------------------------------------------

def test_risk_identified_creates_risk(agent, repo):
    evt = _make_event(
        OrganizationEventType.RISK_IDENTIFIED,
        "Database connection pool saturation under peak load",
        metadata={"severity": "critical", "assignee": "db-admin"},
    )

    res = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="risk-evt-1",
        correlation_id="corr-risk-1",
    )

    assert res.operation == "created"
    assert res.status == OperationalItemStatus.OPEN
    assert res.item.item_type == OperationalItemType.RISK
    assert res.item.priority == OperationalItemPriority.CRITICAL

    risks = agent.get_open_risks()
    assert len(risks) == 1
    assert risks[0].summary == "Database connection pool saturation under peak load"


def test_risk_replay_does_not_duplicate(agent, repo):
    evt = _make_event(
        OrganizationEventType.RISK_IDENTIFIED,
        "Potential memory leak in indexing worker",
        metadata={"severity": "high"},
    )

    res1 = agent.process_event(
        evt,
        source_type="github",
        source_event_id="gh-issue-42",
        correlation_id="corr-leak-42",
    )
    assert res1.operation == "created"

    res2 = agent.process_event(
        evt,
        source_type="github",
        source_event_id="gh-issue-42",
        correlation_id="corr-leak-42",
    )
    assert res2.operation == "no_op"
    assert res2.idempotent is True
    assert len(agent.get_open_risks()) == 1


def test_risk_lifecycle_transitions(agent, repo):
    # Register risk
    evt_risk = _make_event(
        OrganizationEventType.RISK_IDENTIFIED,
        "SSL certificate expires in 7 days",
        metadata={"severity": "high"},
    )
    res_risk = agent.process_event(
        evt_risk,
        source_type="slack",
        source_event_id="sec-alert-1",
        correlation_id="ssl-cert-risk",
    )
    assert res_risk.status == OperationalItemStatus.OPEN

    # Transition to IN_PROGRESS
    evt_prog = _make_event(
        OrganizationEventType.RISK_IDENTIFIED,
        "SSL certificate renewal started",
        metadata={"status": "in_progress"},
    )
    res_prog = agent.process_event(
        evt_prog,
        source_type="slack",
        source_event_id="sec-alert-2",
        correlation_id="ssl-cert-risk",
    )
    assert res_prog.status == OperationalItemStatus.IN_PROGRESS

    # Transition to MITIGATED
    evt_mit = _make_event(
        OrganizationEventType.RISK_IDENTIFIED,
        "New SSL certificates provisioned and rotated",
        metadata={"status": "mitigated"},
    )
    res_mit = agent.process_event(
        evt_mit,
        source_type="slack",
        source_event_id="sec-alert-3",
        correlation_id="ssl-cert-risk",
    )
    assert res_mit.status == OperationalItemStatus.MITIGATED

    # Transition to CLOSED
    evt_close = _make_event(
        OrganizationEventType.RISK_IDENTIFIED,
        "SSL renewal verified on production",
        metadata={"status": "closed"},
    )
    res_close = agent.process_event(
        evt_close,
        source_type="slack",
        source_event_id="sec-alert-4",
        correlation_id="ssl-cert-risk",
    )
    assert res_close.status == OperationalItemStatus.CLOSED

    # Should no longer be in open risks
    assert len(agent.get_open_risks()) == 0


# -----------------------------------------------------------------------------
# K & L: CORRELATION & PROVENANCE
# -----------------------------------------------------------------------------

def test_event_to_operational_correlation_and_provenance(agent, repo):
    corr_id = "project-alpha-deploy"

    evt1 = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Build deployment artifact",
        metadata={"assignee": "ci-bot"},
        evidence=["git commit abc1234"],
    )
    res1 = agent.process_event(
        evt1,
        source_type="github",
        source_event_id="gh-1",
        correlation_id=corr_id,
    )

    evt2 = _make_event(
        OrganizationEventType.TASK_UPDATED,
        "Deploy artifact to staging",
        metadata={"status": "in_progress"},
        evidence=["circleci build #42"],
    )
    res2 = agent.process_event(
        evt2,
        source_type="circleci",
        source_event_id="ci-42",
        correlation_id=corr_id,
    )

    assert res2.affected_item_id == res1.affected_item_id
    item = repo.find_by_id(res1.affected_item_id)
    assert item is not None
    assert item.metadata.get("correlation_id") == corr_id
    assert "git commit abc1234" in item.evidence
    assert "circleci build #42" in item.evidence


# -----------------------------------------------------------------------------
# M: INVALID LIFECYCLE TRANSITION
# -----------------------------------------------------------------------------

def test_invalid_lifecycle_transition_raises(agent, repo):
    evt_create = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Finalize marketing budget",
    )
    res_create = agent.process_event(
        evt_create,
        source_type="email",
        source_event_id="mkt-1",
        correlation_id="mkt-budget",
    )

    # Complete the task
    evt_comp = _make_event(
        OrganizationEventType.TASK_COMPLETED,
        "Finalize marketing budget",
    )
    agent.process_event(
        evt_comp,
        source_type="email",
        source_event_id="mkt-2",
        correlation_id="mkt-budget",
    )

    # Attempt to transition completed task back to in_progress directly via update
    evt_invalid = _make_event(
        OrganizationEventType.TASK_UPDATED,
        "Finalize marketing budget",
        metadata={"status": "in_progress"},
    )
    with pytest.raises(InvalidLifecycleTransitionError):
        agent.process_event(
            evt_invalid,
            source_type="email",
            source_event_id="mkt-3",
            correlation_id="mkt-budget",
        )


# -----------------------------------------------------------------------------
# N: UNSUPPORTED EVENT BEHAVIOR
# -----------------------------------------------------------------------------

def test_unsupported_event_behavior(agent):
    evt = _make_event(
        OrganizationEventType.QUESTION_ASKED,
        "What is our revenue target?",
    )

    # Should raise UnsupportedOperationalEventError when raise_on_unsupported=True
    with pytest.raises(UnsupportedOperationalEventError):
        agent.process_event(
            evt,
            source_type="slack",
            source_event_id="q-1",
            raise_on_unsupported=True,
        )

    # Should return ignored result when raise_on_unsupported=False (pipeline mode)
    res = agent.process_event(
        evt,
        source_type="slack",
        source_event_id="q-1",
        raise_on_unsupported=False,
    )
    assert res.operation == "ignored"
    assert res.idempotent is True
    assert res.affected_item_id is None


# -----------------------------------------------------------------------------
# O: MISSING REFERENCED ITEM BEHAVIOR
# -----------------------------------------------------------------------------

def test_missing_referenced_item_raises_when_explicit_id_provided(agent):
    evt = _make_event(
        OrganizationEventType.TASK_COMPLETED,
        "Resolve incident #999",
        metadata={"item_id": "non-existent-uuid-999"},
    )
    with pytest.raises(OperationalItemNotFoundError):
        agent.process_event(
            evt,
            source_type="pagerduty",
            source_event_id="pd-999",
        )


# -----------------------------------------------------------------------------
# REALISTIC MULTI-EVENT LIFECYCLES
# -----------------------------------------------------------------------------

def test_realistic_multi_event_task_lifecycle(agent, repo):
    # TASK_CREATED -> TASK_UPDATED -> TASK_COMPLETED
    corr = "infra-upgrade-2026"

    # 1. Created
    res1 = agent.process_event(
        _make_event(OrganizationEventType.TASK_CREATED, "Upgrade PostgreSQL to v16"),
        source_type="slack",
        source_event_id="ev-1",
        correlation_id=corr,
    )
    assert res1.operation == "created"

    # 2. Updated to in progress
    res2 = agent.process_event(
        _make_event(
            OrganizationEventType.TASK_UPDATED,
            "Upgrade PostgreSQL to v16 (migration running)",
            metadata={"status": "in_progress", "priority": "high"},
        ),
        source_type="slack",
        source_event_id="ev-2",
        correlation_id=corr,
    )
    assert res2.operation == "updated"

    # 3. Completed
    res3 = agent.process_event(
        _make_event(OrganizationEventType.TASK_COMPLETED, "Upgrade PostgreSQL to v16"),
        source_type="slack",
        source_event_id="ev-3",
        correlation_id=corr,
    )
    assert res3.operation == "completed"

    # Exactly 1 operational item exists throughout the entire lifecycle
    assert res1.affected_item_id == res2.affected_item_id == res3.affected_item_id
    item = repo.find_by_id(res1.affected_item_id)
    assert item is not None
    assert item.status == OperationalItemStatus.COMPLETED


def test_realistic_multi_event_risk_lifecycle(agent, repo):
    # RISK_IDENTIFIED -> updated to in_progress -> mitigated -> closed
    corr = "risk-api-rate-limit"

    r1 = agent.process_event(
        _make_event(
            OrganizationEventType.RISK_IDENTIFIED,
            "Third-party API rate limit approaching threshold",
            metadata={"severity": "high"},
        ),
        source_type="monitoring",
        source_event_id="alert-1",
        correlation_id=corr,
    )
    assert r1.operation == "created"

    r2 = agent.process_event(
        _make_event(
            OrganizationEventType.RISK_IDENTIFIED,
            "Implemented request throttling and local caching",
            metadata={"status": "mitigated"},
        ),
        source_type="monitoring",
        source_event_id="alert-2",
        correlation_id=corr,
    )
    assert r2.operation == "transitioned"

    assert r1.affected_item_id == r2.affected_item_id
    risk = repo.find_by_id(r1.affected_item_id)
    assert risk.status == OperationalItemStatus.MITIGATED


# -----------------------------------------------------------------------------
# OVERDUE & REMINDERS
# -----------------------------------------------------------------------------

def test_overdue_items_detection(agent, repo):
    past_due = datetime.now(timezone.utc) - timedelta(days=1)
    future_due = datetime.now(timezone.utc) + timedelta(days=2)

    item1 = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Overdue task 1",
        due_at=past_due,
    )
    item2 = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Future task 2",
        due_at=future_due,
    )
    repo.save(item1)
    repo.save(item2)

    overdue = agent.get_overdue_items()
    assert len(overdue) == 1
    assert overdue[0].summary == "Overdue task 1"


def test_reminder_scheduling(agent, repo, reminder_service):
    task = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Review compliance report",
    )
    saved = repo.save(task)

    reminder = agent.schedule_task_reminder(
        str(saved.identifier.graph_id),
        target_user_id="U_ALICE",
        creator_user_id="U_BOB",
        channel_id="C_COMPLIANCE",
        source_message_ts="1234567890.123",
    )

    assert reminder is not None
    assert len(reminder_service.created_reminders) == 1
    assert reminder_service.created_reminders[0]["task"] == "Review compliance report"
    assert reminder_service.created_reminders[0]["target_user_id"] == "U_ALICE"


# -----------------------------------------------------------------------------
# EVIDENCE RETRIEVAL & ASK
# -----------------------------------------------------------------------------

def test_operational_evidence_and_ask(agent, repo):
    task = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Audit user permission policies",
        owner_name="DevOps Team",
    )
    repo.save(task)

    q = Question(text="What is the audit task?")
    evidence = agent.retrieve_evidence(q)
    assert any("Audit user permission policies" in ev for ev in evidence)

    ans = agent.ask(q)
    assert ans["question"] == "What is the audit task?"
    assert len(ans["evidence"]) > 0
    assert ans["summary"]["open_task_count"] >= 1


def test_task_created_normalizes_identifier_correlation_id(agent, repo):
    correlation = Identifier(business_id="calendar-event-123")
    event = _make_event(
        OrganizationEventType.TASK_CREATED,
        "Review the calendar integration",
    )

    result = agent.process_event(
        event,
        source_type="slack",
        source_event_id="evt-identifier-correlation",
        correlation_id=correlation,
    )

    assert result.operation == "created"
    assert result.item is not None
    assert result.item.metadata["correlation_id"] == "calendar-event-123"
    assert isinstance(result.item.metadata["correlation_id"], str)

    saved = repo.find_by_id(result.affected_item_id)
    assert saved is not None
    assert saved.metadata["correlation_id"] == "calendar-event-123"
    assert isinstance(saved.metadata["correlation_id"], str)
