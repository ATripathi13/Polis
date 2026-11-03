from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from domain.common.identifier import Identifier
from domain.observation import Observation, ObservationType
from domain.organization import OrganizationEvent, OrganizationEventType
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.operations.repositories.in_memory_operational_item_repository import (
    InMemoryOperationalItemRepository,
)
from domain.reasoning.value_objects import Question
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from application.identity import (
    CanonicalIdentityService,
    IdentityResolutionStatus,
)
from application.operations import OperationalItemService, OperationsAgent
from domain.observation.rules.operational_observation_rule import (
    OperationalObservationRule,
)


@pytest.fixture
def repo():
    return InMemoryOperationalItemRepository()


@pytest.fixture
def mock_identity_service():
    service = MagicMock(spec=CanonicalIdentityService)

    def _resolve_name(query, platform="slack"):
        cleaned = query.strip().lower()
        if "hemant" in cleaned and "vijay" not in cleaned:
            mock_id = MagicMock()
            mock_id.internal_id = "U_HEMANT"
            mock_id.canonical_name = "Hemant Sharma"
            mock_id.resolution_status = IdentityResolutionStatus.RESOLVED
            return mock_id
        if "vijay" in cleaned and "hemant" not in cleaned:
            mock_id = MagicMock()
            mock_id.internal_id = "U_VIJAY"
            mock_id.canonical_name = "Vijay Kumar"
            mock_id.resolution_status = IdentityResolutionStatus.RESOLVED
            return mock_id
        if "bob" in cleaned:
            mock_id = MagicMock()
            mock_id.internal_id = "U_BOB"
            mock_id.canonical_name = "Bob"
            mock_id.resolution_status = IdentityResolutionStatus.RESOLVED
            return mock_id
        if "alice" in cleaned:
            mock_id = MagicMock()
            mock_id.internal_id = "U_ALICE"
            mock_id.canonical_name = "Alice"
            mock_id.resolution_status = IdentityResolutionStatus.RESOLVED
            return mock_id
        # Ambiguous or unknown
        return None

    def _resolve_user(user_id, platform="slack", display_name_hint=None, email_hint=None):
        mock_id = MagicMock()
        mock_id.internal_id = user_id
        mock_id.canonical_name = display_name_hint or user_id
        mock_id.resolution_status = IdentityResolutionStatus.RESOLVED
        return mock_id

    service.resolve_user_by_name_or_mention.side_effect = _resolve_name
    service.resolve_user.side_effect = _resolve_user
    service.get_all_identifiers_for_user.side_effect = lambda uid: {uid}
    return service


@pytest.fixture
def operations_agent(repo, mock_identity_service):
    service = OperationalItemService(repo)
    return OperationsAgent(
        repository=repo,
        operational_item_service=service,
        identity_service=mock_identity_service,
    )


def _make_comm_event(
    body: str,
    actor_id: str = "U_AUTHOR",
    actor_name: str = "Author Name",
    channel_id: str = "C123",
    source_event_id: str = "ts_101",
) -> CommunicationEvent:
    return CommunicationEvent.create(
        correlation_id=Identifier(business_id="corr-1"),
        source=EventSource.SLACK,
        source_event_id=source_event_id,
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id=actor_id,
                external_ids={"slack": actor_id},
            ),
            display_name=actor_name,
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id=channel_id,
                external_ids={"slack": channel_id},
            ),
            name="general",
            channel_type="public",
        ),
        content=Content(body=body),
    )


# =============================================================================
# 1. OBSERVATION EXTRACTION & CONVERSATIONAL SCREENING
# =============================================================================

def test_conversational_questions_to_polis_are_screened_out():
    mock_understanding = MagicMock()
    # Even if LLM would have returned task, rule screening must reject it
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "help follow up",
    }
    rule = OperationalObservationRule(mock_understanding)

    comm1 = _make_comm_event("Can you tell me what you can help me with?")
    comm2 = _make_comm_event("Can you help me follow up on a pending task?")
    comm3 = _make_comm_event("Ok sir I will check with it")

    assert rule.extract(comm1) == []
    assert rule.extract(comm2) == []
    assert rule.extract(comm3) == []
    mock_understanding.analyze.assert_not_called()


def test_observation_extracts_metadata_and_actor_context():
    mock_understanding = MagicMock()
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "Complete the API integration",
        "confidence": 0.95,
        "ownership_type": "self_commitment",
    }
    rule = OperationalObservationRule(mock_understanding)

    comm = _make_comm_event(
        "I will complete the API integration by Friday.",
        actor_id="U_DEV_1",
        actor_name="Dev One",
        channel_id="C_DEV",
        source_event_id="ts_999",
    )

    observations = rule.extract(comm)
    assert len(observations) == 1
    obs = observations[0]
    assert obs.observation_type == ObservationType.TASK
    assert obs.summary == "Complete the API integration"
    assert obs.metadata["actor_id"] == "U_DEV_1"
    assert obs.metadata["actor_name"] == "Dev One"
    assert obs.metadata["channel_id"] == "C_DEV"
    assert obs.metadata["ownership_type"] == "self_commitment"
    assert obs.metadata["owner_id"] == "U_DEV_1"


def test_llm_org_wide_ownership_type_for_personal_calendar_task_remains_personal():
    mock_understanding = MagicMock()
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "Block calendar for team sync",
        "confidence": 0.9,
        "ownership_type": "organization_wide",
    }
    rule = OperationalObservationRule(mock_understanding)

    comm = _make_comm_event(
        "I will block time on my calendar for our team sync.",
        actor_id="U_ALICE",
        actor_name="Alice",
        channel_id="C_TEAM",
        source_event_id="ts_cal_1",
    )

    observations = rule.extract(comm)
    assert len(observations) == 1
    obs = observations[0]
    # Deterministic check fails because message lacks org-wide token; falls through to self_commitment
    assert obs.metadata["ownership_type"] != "organization_wide"
    assert obs.metadata["ownership_type"] == "self_commitment"
    assert obs.metadata["is_organization_wide"] is False
    assert obs.metadata["scope"] == "personal"
    assert obs.metadata["owner_id"] == "U_ALICE"
    assert obs.metadata["owner_name"] == "Alice"


def test_llm_is_org_wide_boolean_for_personal_holiday_task_remains_personal():
    mock_understanding = MagicMock()
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "Take holiday leave next Monday",
        "confidence": 0.9,
        "is_organization_wide": True,
        "ownership_type": "none",
    }
    rule = OperationalObservationRule(mock_understanding)

    comm = _make_comm_event(
        "I am taking holiday leave next Monday.",
        actor_id="U_BOB",
        actor_name="Bob",
        channel_id="C_TEAM",
        source_event_id="ts_hol_1",
    )

    observations = rule.extract(comm)
    assert len(observations) == 1
    obs = observations[0]
    # LLM is_organization_wide boolean is ignored; deterministic check fails
    assert obs.metadata["ownership_type"] != "organization_wide"
    assert obs.metadata["is_organization_wide"] is False
    assert obs.metadata["scope"] == "personal"


def test_explicit_for_the_whole_organization_is_classified_organization_wide():
    mock_understanding = MagicMock()
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "Publish company holiday schedule",
        "confidence": 0.95,
        "ownership_type": "none",
    }
    rule = OperationalObservationRule(mock_understanding)

    comm = _make_comm_event(
        "Publish company holiday schedule for the whole organization by Friday.",
        actor_id="U_HR",
        actor_name="HR Lead",
        channel_id="C_ANNOUNCE",
        source_event_id="ts_org_wide_1",
    )

    observations = rule.extract(comm)
    assert len(observations) == 1
    obs = observations[0]
    # Deterministic check succeeds on "for the whole organization"
    assert obs.metadata["ownership_type"] == "organization_wide"
    assert obs.metadata["is_organization_wide"] is True
    assert obs.metadata["scope"] == "organization"


def test_personal_calendar_or_holiday_wording_alone_does_not_establish_org_scope():
    mock_understanding = MagicMock()
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "Mark holiday coverage on calendar",
        "confidence": 0.85,
    }
    rule = OperationalObservationRule(mock_understanding)

    # Contains both 'calendar' and 'holiday' but without organization-wide scope tokens
    comm = _make_comm_event(
        "Please check your calendar for holiday coverage during Diwali week.",
        actor_id="U_LEAD",
        actor_name="Team Lead",
        channel_id="C_PROJECT",
        source_event_id="ts_cal_hol_1",
    )

    observations = rule.extract(comm)
    assert len(observations) == 1
    obs = observations[0]
    assert obs.metadata["ownership_type"] != "organization_wide"
    assert obs.metadata["is_organization_wide"] is False
    assert obs.metadata["scope"] == "personal"


def test_individual_company_holiday_request_remains_personal():
    mock_understanding = MagicMock()
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "Request company holiday next Monday",
        "confidence": 0.9,
        "ownership_type": "organization_wide",
        "is_organization_wide": True,
    }
    rule = OperationalObservationRule(mock_understanding)

    comm = _make_comm_event(
        "I need to request a company holiday next Monday.",
        actor_id="U_EMP_1",
        actor_name="Employee One",
        channel_id="C_TEAM",
        source_event_id="ts_req_hol_1",
    )

    observations = rule.extract(comm)
    assert len(observations) == 1
    obs = observations[0]
    assert obs.metadata["ownership_type"] != "organization_wide"
    assert obs.metadata["is_organization_wide"] is False
    assert obs.metadata["scope"] == "personal"


def test_publish_company_holiday_schedule_for_all_employees_is_org_wide():
    mock_understanding = MagicMock()
    mock_understanding.analyze.return_value = {
        "is_operational": True,
        "type": "task",
        "summary": "Publish the company holiday schedule for all employees",
        "confidence": 0.95,
        "ownership_type": "none",
    }
    rule = OperationalObservationRule(mock_understanding)

    comm = _make_comm_event(
        "Publish the company holiday schedule for all employees.",
        actor_id="U_HR",
        actor_name="HR Lead",
        channel_id="C_ANNOUNCE",
        source_event_id="ts_sched_all_1",
    )

    observations = rule.extract(comm)
    assert len(observations) == 1
    obs = observations[0]
    assert obs.metadata["ownership_type"] == "organization_wide"
    assert obs.metadata["is_organization_wide"] is True
    assert obs.metadata["scope"] == "organization"


# =============================================================================
# 2. OWNERSHIP RULES A-E
# =============================================================================

def test_rule_a_explicit_assignment(operations_agent, repo):
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Prepare the deployment report by tomorrow",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Prepare the deployment report by tomorrow",
                confidence=0.9,
                evidence=["ts_rule_a"],
                metadata={
                    "actor_id": "U_MANAGER",
                    "actor_name": "Manager",
                    "ownership_type": "explicit_assignment",
                    "assignee": "Hemant",
                },
            )
        ],
    )

    result = operations_agent.process_event(event, source_type="slack", source_event_id="ts_rule_a")
    assert result.operation == "created"
    assert result.item is not None
    # Hemant is resolved via mock identity service
    assert result.item.owner_id == "U_HEMANT"
    assert result.item.owner_name == "Hemant Sharma"


def test_rule_b_explicit_self_commitment(operations_agent, repo):
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Complete the API integration",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Complete the API integration",
                confidence=0.95,
                evidence=["ts_rule_b"],
                metadata={
                    "actor_id": "U_DEV_1",
                    "actor_name": "Dev One",
                    "ownership_type": "self_commitment",
                },
            )
        ],
    )

    result = operations_agent.process_event(event, source_type="slack", source_event_id="ts_rule_b")
    assert result.operation == "created"
    assert result.item is not None
    assert result.item.owner_id == "U_DEV_1"
    assert result.item.owner_name == "Dev One"


def test_rule_c_author_without_assignment_does_not_own_task(operations_agent, repo):
    # Author says: "I will instruct Hemant or Vijay to connect my PC remotely."
    # Author is delegating, not completing the remote PC setup.
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Connect PC remotely",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Connect PC remotely",
                confidence=0.85,
                evidence=["ts_rule_c"],
                metadata={
                    "actor_id": "U_AUTHOR",
                    "actor_name": "Author",
                    "ownership_type": "unassigned",
                    "original_text": "I will instruct Hemant or Vijay to connect my PC remotely.",
                },
            )
        ],
    )

    result = operations_agent.process_event(event, source_type="slack", source_event_id="ts_rule_c")
    assert result.operation == "created"
    assert result.item is not None
    # Crucial: Author must NOT become owner!
    assert result.item.owner_id == ""
    assert result.item.owner_name == ""


def test_rule_d_ambiguous_assignment_remains_unassigned(operations_agent, repo):
    # Mentioning multiple candidates ambiguously
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Follow up on server error",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Follow up on server error",
                confidence=0.8,
                evidence=["ts_rule_d"],
                metadata={
                    "actor_id": "U_AUTHOR",
                    "actor_name": "Author",
                    "ownership_type": "explicit_assignment",
                    "assignee": "Hemant or Vijay",  # Ambiguous -> mock returns None
                },
            )
        ],
    )

    result = operations_agent.process_event(event, source_type="slack", source_event_id="ts_rule_d")
    assert result.operation == "created"
    assert result.item is not None
    assert result.item.owner_id == ""
    assert result.item.owner_name == ""


def test_rule_e_organization_wide_calendar_entry(operations_agent, repo):
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Add company calendar entry for Diwali for the whole organization",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Add company calendar entry for Diwali for the whole organization",
                confidence=0.9,
                evidence=["ts_rule_e"],
                metadata={
                    "actor_id": "U_AUTHOR",
                    "actor_name": "Author",
                    "ownership_type": "organization_wide",
                    "is_organization_wide": True,
                    "scope": "organization",
                },
            )
        ],
    )

    result = operations_agent.process_event(event, source_type="slack", source_event_id="ts_rule_e")
    assert result.operation == "created"
    assert result.item is not None
    assert result.item.owner_id == ""
    assert result.item.owner_name == ""


# =============================================================================
# 3. DEDUPLICATION
# =============================================================================

def test_deduplication_of_repeated_calendar_requests(operations_agent, repo):
    event1 = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Add Diwali holiday to company calendar",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Add Diwali holiday to company calendar",
                confidence=0.9,
                evidence=["ts_diwali_1"],
                metadata={"is_organization_wide": True},
            )
        ],
    )
    res1 = operations_agent.process_event(event1, source_type="slack", source_event_id="ts_diwali_1")
    assert res1.operation == "created"

    # Second identical event arrives
    event2 = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Add Diwali holiday to company calendar",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Add Diwali holiday to company calendar",
                confidence=0.9,
                evidence=["ts_diwali_2"],
                metadata={"is_organization_wide": True},
            )
        ],
    )
    res2 = operations_agent.process_event(event2, source_type="slack", source_event_id="ts_diwali_2")
    assert res2.operation == "no_op"
    assert res2.idempotent is True
    # Still only 1 task in repository
    assert len(repo.find_open(item_type=OperationalItemType.TASK)) == 1


# =============================================================================
# 4. PERSONAL RETRIEVAL & ISOLATION IN OPERATIONAL ITEM SERVICE
# =============================================================================

def test_personal_task_retrieval_is_strictly_scoped_to_authenticated_user(repo):
    service = OperationalItemService(repo)

    # Seed tasks:
    # 1. Employee A task
    task_a = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Task for Alice",
        owner_id="U_ALICE",
        owner_name="Alice",
    )
    repo.save(task_a)

    # 2. Employee B task
    task_b = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Task for Bob",
        owner_id="U_BOB",
        owner_name="Bob",
    )
    repo.save(task_b)

    # 3. Unassigned task
    task_unassigned = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Connect remote PC",
        owner_id="",
        owner_name="",
    )
    repo.save(task_unassigned)

    # 4. Organization Decision
    decision = OperationalItem.create(
        item_type=OperationalItemType.DECISION,
        summary="Approve migration budget",
        owner_id="",
        owner_name="",
    )
    repo.save(decision)

    # Alice asks: "What should I work on today?"
    q_alice = Question(text="What should I work on today?", user_id="U_ALICE", user_name="Alice")
    ev_alice = service.retrieve_evidence(q_alice)

    # Alice must ONLY receive Alice's task
    assert any("Task for Alice" in ev for ev in ev_alice)
    assert not any("Task for Bob" in ev for ev in ev_alice)
    assert not any("Connect remote PC" in ev for ev in ev_alice)

    # Bob asks: "What are my tasks?"
    q_bob = Question(text="What are my tasks?", user_id="U_BOB", user_name="Bob")
    ev_bob = service.retrieve_evidence(q_bob)

    assert any("Task for Bob" in ev for ev in ev_bob)
    assert not any("Task for Alice" in ev for ev in ev_bob)

    # Unauthenticated user asking for personal tasks never triggers org task dump
    q_unknown = Question(text="What are my tasks?", user_id="", user_name="")
    ev_unknown = service.retrieve_evidence(q_unknown)
    assert any("could not be verified" in ev for ev in ev_unknown)
    assert not any("Task for Alice" in ev for ev in ev_unknown)
    assert not any("Task for Bob" in ev for ev in ev_unknown)


def test_organization_decisions_and_risks_remain_separate_context(repo):
    service = OperationalItemService(repo)

    decision = OperationalItem.create(
        item_type=OperationalItemType.DECISION,
        summary="Adopt PostgreSQL 16",
        owner_id="",
        owner_name="",
    )
    repo.save(decision)

    risk = OperationalItem.create(
        item_type=OperationalItemType.RISK,
        summary="API latency exceeds SLA",
        owner_id="",
        owner_name="",
    )
    repo.save(risk)

    q_decisions = Question(text="What decisions were made?", user_id="U_ALICE")
    ev_dec = service.retrieve_evidence(q_decisions)
    assert any("[Organization Decision]" in ev for ev in ev_dec)
    assert any("Adopt PostgreSQL 16" in ev for ev in ev_dec)

    q_risks = Question(text="What risks are tracked?", user_id="U_ALICE")
    ev_risk = service.retrieve_evidence(q_risks)
    assert any("[Organization Risk]" in ev for ev in ev_risk)
    assert any("API latency exceeds SLA" in ev for ev in ev_risk)


def test_cross_platform_task_retrieval_consistency(repo):
    """
    Point 2 Architecture Requirement:
    Prove that an employee assigned a task via one platform (e.g. Teams)
    consistently retrieves their task when querying via another platform (e.g. Slack)
    because all employee ownership comparisons resolve to the canonical identifier.
    """
    identity_service = CanonicalIdentityService()

    # Pre-register user on Slack and Teams with same email
    identity_service.resolve_user(
        "U_ALICE_SLACK",
        platform="slack",
        display_name_hint="Alice Walker",
        email_hint="alice.walker@company.com",
    )
    identity_service.resolve_user(
        "29:teams_alice_walker",
        platform="microsoft_teams",
        display_name_hint="Alice Walker",
        email_hint="alice.walker@company.com",
    )

    service = OperationalItemService(repo, identity_service=identity_service)

    # Task created with canonical employee ID
    task = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Configure SAML SSO for staging",
        owner_id="emp_alice.walker@company.com",
        owner_name="Alice Walker",
    )
    repo.save(task)

    # 1. Querying from Slack using Slack user ID
    q_slack = Question(text="What are my tasks?", user_id="U_ALICE_SLACK", user_name="Alice")
    ev_slack = service.retrieve_evidence(q_slack)
    assert any("Configure SAML SSO for staging" in ev for ev in ev_slack)

    # 2. Querying from Teams using Teams user ID
    q_teams = Question(text="What are my tasks?", user_id="29:teams_alice_walker", user_name="Alice Walker")
    ev_teams = service.retrieve_evidence(q_teams)
    assert any("Configure SAML SSO for staging" in ev for ev in ev_teams)


def test_requester_vs_target_task_and_overdue_retrieval(repo, mock_identity_service):
    """
    Open employee access:
    1. Alice asks for her tasks while Bob is set as target -> Alice's tasks only.
    2. Alice asks for Bob's tasks -> Bob's tasks only.
    3. Alice asks for her overdue tasks while Bob is set as target -> Alice's overdue tasks only.
    4. Alice asks for Bob's overdue tasks -> Bob's overdue tasks only.
    5. Unresolved target -> clarification, no organization-wide disclosure.
    6. General organization-wide task query -> existing behavior preserved.
    """
    from datetime import timedelta
    service = OperationalItemService(repo, identity_service=mock_identity_service)
    now = datetime.now(timezone.utc)

    # Seed tasks:
    # 1. Alice open task
    task_alice = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Alice: Update deployment manifests",
        owner_id="U_ALICE",
        owner_name="Alice",
    )
    repo.save(task_alice)

    # 2. Alice overdue task
    task_alice_overdue = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Alice: Fix SSL certificate expiry",
        owner_id="U_ALICE",
        owner_name="Alice",
        due_at=now - timedelta(hours=5),
    )
    repo.save(task_alice_overdue)

    # 3. Bob open task
    task_bob = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Bob: Migrate Redis caches",
        owner_id="U_BOB",
        owner_name="Bob",
    )
    repo.save(task_bob)

    # 4. Bob overdue task
    task_bob_overdue = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Bob: Patch PostgreSQL connection pooler",
        owner_id="U_BOB",
        owner_name="Bob",
        due_at=now - timedelta(hours=3),
    )
    repo.save(task_bob_overdue)

    # 5. General unassigned task
    task_unassigned = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="General: Audit organization log retention",
        owner_id="",
        owner_name="",
    )
    repo.save(task_unassigned)

    # --- 1. Alice asks for her tasks while Bob is set as the target -> Alice's tasks only ---
    q_alice_self = Question(
        text="What are my tasks?",
        user_id="U_ALICE",
        user_name="Alice",
        target_user_id="U_BOB",
        target_user_name="Bob",
    )
    ev_alice_self = service.retrieve_evidence(q_alice_self)
    assert any("Alice: Update deployment manifests" in ev for ev in ev_alice_self)
    assert not any("Bob: Migrate Redis caches" in ev for ev in ev_alice_self)
    assert not any("General: Audit organization log retention" in ev for ev in ev_alice_self)

    # Also self-reference with "What should I work on today?"
    q_alice_today = Question(
        text="What should I work on today?",
        user_id="U_ALICE",
        user_name="Alice",
        target_user_id="U_BOB",
    )
    ev_alice_today = service.retrieve_evidence(q_alice_today)
    assert any("Alice: Update deployment manifests" in ev for ev in ev_alice_today)
    assert not any("Bob: Migrate Redis caches" in ev for ev in ev_alice_today)

    # Explicit named target must take precedence over the broad "today" wording.
    q_bob_today = Question(
        text="What is Bob working on today?",
        user_id="U_ALICE",
        user_name="Alice",
    )
    ev_bob_today = service.retrieve_evidence(q_bob_today)
    assert any("Bob: Migrate Redis caches" in ev for ev in ev_bob_today)
    assert not any("Alice: Update deployment manifests" in ev for ev in ev_bob_today)
    assert not any("General: Audit organization log retention" in ev for ev in ev_bob_today)
    # --- 2. Alice asks for Bob's tasks -> Bob's tasks only ---
    # With explicit target_user_id
    q_bob_tasks = Question(
        text="What are Bob's tasks?",
        user_id="U_ALICE",
        user_name="Alice",
        target_user_id="U_BOB",
        target_user_name="Bob",
    )
    ev_bob_tasks = service.retrieve_evidence(q_bob_tasks)
    assert any("Bob: Migrate Redis caches" in ev for ev in ev_bob_tasks)
    assert not any("Alice: Update deployment manifests" in ev for ev in ev_bob_tasks)
    assert not any("General: Audit organization log retention" in ev for ev in ev_bob_tasks)

    # Without target_user_id pre-set, relying on identity service resolving "Bob" from text
    q_bob_by_name = Question(
        text="What are Bob's tasks?",
        user_id="U_ALICE",
        user_name="Alice",
    )
    ev_bob_by_name = service.retrieve_evidence(q_bob_by_name)
    assert any("Bob: Migrate Redis caches" in ev for ev in ev_bob_by_name)
    assert not any("Alice: Update deployment manifests" in ev for ev in ev_bob_by_name)

    # --- 3. Alice asks for her overdue tasks while Bob is set as the target -> Alice's overdue tasks only ---
    q_alice_overdue = Question(
        text="What are my overdue tasks?",
        user_id="U_ALICE",
        user_name="Alice",
        target_user_id="U_BOB",
        target_user_name="Bob",
    )
    ev_alice_overdue = service.retrieve_evidence(q_alice_overdue)
    assert any("Alice: Fix SSL certificate expiry" in ev for ev in ev_alice_overdue)
    assert not any("Bob: Patch PostgreSQL connection pooler" in ev for ev in ev_alice_overdue)

    # --- 4. Alice asks for Bob's overdue tasks -> Bob's overdue tasks only ---
    q_bob_overdue = Question(
        text="What are Bob's overdue tasks?",
        user_id="U_ALICE",
        user_name="Alice",
        target_user_id="U_BOB",
    )
    ev_bob_overdue = service.retrieve_evidence(q_bob_overdue)
    assert any("Bob: Patch PostgreSQL connection pooler" in ev for ev in ev_bob_overdue)
    assert not any("Alice: Fix SSL certificate expiry" in ev for ev in ev_bob_overdue)

    # --- 5. Unresolved target -> clarification, no organization-wide disclosure ---
    q_unresolved = Question(
        text="What are Charlie's tasks?",
        user_id="U_ALICE",
        user_name="Alice",
    )
    ev_unresolved = service.retrieve_evidence(q_unresolved)
    assert len(ev_unresolved) == 1
    assert "Could not resolve target employee 'Charlie'" in ev_unresolved[0]
    assert "clarify" in ev_unresolved[0].lower()
    # Crucial: NO task leakage/disclosure across the organization
    assert not any("Alice" in ev for ev in ev_unresolved)
    assert not any("Bob" in ev for ev in ev_unresolved)
    assert not any("General" in ev for ev in ev_unresolved)

    # Also for overdue tasks with unresolved target
    q_unresolved_overdue = Question(
        text="What are Charlie's overdue tasks?",
        user_id="U_ALICE",
        user_name="Alice",
    )
    ev_unresolved_overdue = service.retrieve_evidence(q_unresolved_overdue)
    assert len(ev_unresolved_overdue) == 1
    assert "Could not resolve target employee 'Charlie'" in ev_unresolved_overdue[0]
    assert not any("Alice" in ev for ev in ev_unresolved_overdue)
    assert not any("Bob" in ev for ev in ev_unresolved_overdue)

    # --- 6. General organization-wide task query -> existing behavior preserved ---
    q_org_tasks = Question(
        text="What tasks are open across the organization?",
        user_id="U_ALICE",
        user_name="Alice",
    )
    ev_org = service.retrieve_evidence(q_org_tasks)
    assert any("Alice: Update deployment manifests" in ev for ev in ev_org)
    assert any("Bob: Migrate Redis caches" in ev for ev in ev_org)
    assert any("General: Audit organization log retention" in ev for ev in ev_org)


def test_cross_event_deduplication_requires_verified_org_scope_and_never_merges_personal_tasks(operations_agent, repo):
    """
    Targeted Correction 1 Regression Test:
    Only merge different source events when BOTH the existing and incoming tasks
    have verified organization-wide scope, with matching normalized summaries.
    Never merge separate personal tasks based on calendar/holiday keywords alone.
    """
    # 1. Two separate personal tasks containing calendar and holiday keywords
    personal_event_1 = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Review team holiday calendar for Diwali",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Review team holiday calendar for Diwali",
                confidence=0.9,
                evidence=["ts_pers_1"],
                metadata={
                    "actor_id": "U_ALICE",
                    "actor_name": "Alice",
                    "ownership_type": "self_commitment",
                    "is_organization_wide": False,
                },
            )
        ],
    )
    res1 = operations_agent.process_event(personal_event_1, source_type="slack", source_event_id="ts_pers_1")
    assert res1.operation == "created"

    personal_event_2 = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Review team holiday calendar for Diwali",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Review team holiday calendar for Diwali",
                confidence=0.9,
                evidence=["ts_pers_2"],
                metadata={
                    "actor_id": "U_BOB",
                    "actor_name": "Bob",
                    "ownership_type": "self_commitment",
                    "is_organization_wide": False,
                },
            )
        ],
    )
    res2 = operations_agent.process_event(personal_event_2, source_type="slack", source_event_id="ts_pers_2")

    # MUST NOT be merged despite matching summary and calendar/holiday keywords!
    assert res2.operation == "created"
    assert res2.idempotent is False
    open_tasks = [t for t in repo.find_open(item_type=OperationalItemType.TASK) if "Review team holiday calendar" in t.summary]
    assert len(open_tasks) == 2

    # 2. In contrast, verified organization-wide tasks with matching summaries ARE deduplicated
    org_event_1 = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Publish official company holiday calendar for 2027",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Publish official company holiday calendar for 2027",
                confidence=0.95,
                evidence=["ts_org_1"],
                metadata={"is_organization_wide": True, "scope": "organization"},
            )
        ],
    )
    res_org_1 = operations_agent.process_event(org_event_1, source_type="slack", source_event_id="ts_org_1")
    assert res_org_1.operation == "created"

    org_event_2 = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Publish official company holiday calendar for 2027",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Publish official company holiday calendar for 2027",
                confidence=0.95,
                evidence=["ts_org_2"],
                metadata={"is_organization_wide": True, "scope": "organization"},
            )
        ],
    )
    res_org_2 = operations_agent.process_event(org_event_2, source_type="slack", source_event_id="ts_org_2")
    assert res_org_2.operation == "no_op"
    assert res_org_2.idempotent is True
    org_tasks = [t for t in repo.find_open(item_type=OperationalItemType.TASK) if "official company holiday calendar" in t.summary]
    assert len(org_tasks) == 1


def test_unresolved_employee_fallback_preserves_unassigned_with_identity_evidence_in_metadata(repo):
    """
    Targeted Correction 2 Regression Test:
    When CanonicalIdentityService is configured but cannot resolve an employee,
    do not persist the raw Slack or Teams ID as the canonical owner.
    Preserve the item as unassigned with the original identity evidence in metadata.
    """
    # Create an identity service where directory lookups fail / return unresolved
    mock_slack = MagicMock()
    mock_slack.get_workspace_users.return_value = []
    unresolving_identity_service = CanonicalIdentityService(slack_identity_service=mock_slack)

    agent = OperationsAgent(
        repository=repo,
        identity_service=unresolving_identity_service,
    )

    # User U_UNKNOWN commits to a task in Slack
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Deploy security patch to Redis cluster",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Deploy security patch to Redis cluster",
                confidence=0.9,
                evidence=["ts_patch_1"],
                metadata={
                    "actor_id": "U_UNKNOWN_BOT_USER",
                    "actor_name": "Unknown Colleague",
                    "channel_id": "C_SECOPS",
                    "ownership_type": "self_commitment",
                    "original_text": "I will deploy security patch to Redis cluster",
                },
            )
        ],
    )

    result = agent.process_event(event, source_type="slack", source_event_id="ts_patch_1")
    assert result.operation == "created"
    assert result.item is not None

    # Crucial assertion: Raw Slack ID MUST NOT be persisted as canonical owner
    assert result.item.owner_id == ""
    assert result.item.owner_name == ""

    # Crucial assertion: Original identity evidence MUST be preserved in metadata
    assert result.item.metadata["actor_id"] == "U_UNKNOWN_BOT_USER"
    assert result.item.metadata["actor_name"] == "Unknown Colleague"
    assert result.item.metadata["channel_id"] == "C_SECOPS"
    assert result.item.metadata["original_text"] == "I will deploy security patch to Redis cluster"
