from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.activity import ActivitySource, ActivityType
from domain.activity.aggregates.activity_event import ActivityEvent
from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from infrastructure.database import activity_repository as activity_module
from infrastructure.database import operational_item_repository as operational_module
from infrastructure.database.models import (
    ActivityEventModel,
    OperationalItemModel,
    Base,
)
from infrastructure.database.operational_item_repository import (
    PostgreSQLOperationalItemRepository,
)
from infrastructure.database.activity_repository import PostgreSQLActivityRepository

from application.activity import ActivityService, AttendanceCalculator
from application.operations import OperationsAgent, OperationalItemService
from domain.observation import Observation, ObservationType
from domain.organization import OrganizationEvent, OrganizationEventType


@pytest.fixture
def postgres_repositories(monkeypatch):
    """Use only the explicitly configured isolated polis_test database."""
    database_url = os.environ.get("POLIS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set POLIS_TEST_DATABASE_URL to the isolated polis_test URL.")

    if not database_url.startswith("postgresql+psycopg://"):
        pytest.fail("POLIS_TEST_DATABASE_URL must use postgresql+psycopg://")

    from sqlalchemy.engine import make_url

    parsed_url = make_url(database_url)
    if parsed_url.host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail("POLIS_TEST_DATABASE_URL must point to a local PostgreSQL host.")
    if parsed_url.database != "polis_test":
        pytest.fail("POLIS_TEST_DATABASE_URL must target the 'polis_test' database.")

    engine = create_engine(database_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            database_name = connection.exec_driver_sql(
                "SELECT current_database()"
            ).scalar_one()

        if database_name != "polis_test":
            pytest.fail(
                f"Refusing to write to database {database_name!r}; "
                "expected 'polis_test'."
            )

        Base.metadata.create_all(bind=engine)

        TestSessionLocal = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
        )

        monkeypatch.setattr(
            operational_module, "SessionLocal", TestSessionLocal
        )
        monkeypatch.setattr(activity_module, "SessionLocal", TestSessionLocal)

        yield (
            PostgreSQLOperationalItemRepository(),
            PostgreSQLActivityRepository(),
            TestSessionLocal,
        )
    finally:
        engine.dispose()


def test_operational_item_round_trip_update_and_correlation(
    postgres_repositories,
):
    operations, _, session_factory = postgres_repositories

    unique = uuid4().hex
    correlation_id = f"pg-test-correlation-{unique}"
    item_id = str(uuid4())
    source_event_id = f"pg-test-event-{unique}"
    now = datetime.now(timezone.utc)
    due_at = now + timedelta(days=2)

    item = OperationalItem(
        identifier=Identifier(graph_id=UUID(item_id)),
        item_type=OperationalItemType.TASK,
        summary=f"PostgreSQL persistence test {unique}",
        status=OperationalItemStatus.OPEN,
        priority=OperationalItemPriority.HIGH,
        owner_id=f"pg-test-person-{unique}",
        owner_name="PostgreSQL Test Person",
        due_at=due_at,
        source_event_id=source_event_id,
        source_type="postgres-integration-test",
        confidence=0.87,
        evidence=[f"evidence-{unique}"],
        metadata={"correlation_id": correlation_id, "test_run": unique},
    )

    try:
        saved = operations.save(item)
        assert saved.identifier.graph_id == item.identifier.graph_id

        # A new repository call creates a separate session.
        retrieved = operations.find_by_id(item_id)
        assert retrieved is not None
        assert retrieved.summary == item.summary
        assert retrieved.owner_id == item.owner_id
        assert retrieved.priority == OperationalItemPriority.HIGH
        assert retrieved.evidence == item.evidence
        assert retrieved.metadata["correlation_id"] == correlation_id

        updated = OperationalItem(
            identifier=Identifier(graph_id=UUID(item_id)),
            item_type=OperationalItemType.TASK,
            summary=f"Updated PostgreSQL test {unique}",
            status=OperationalItemStatus.IN_PROGRESS,
            priority=OperationalItemPriority.MEDIUM,
            owner_id=f"pg-test-owner-updated-{unique}",
            owner_name="Updated Test Owner",
            due_at=due_at,
            source_event_id=source_event_id,
            source_type="postgres-integration-test",
            confidence=0.93,
            evidence=[f"updated-evidence-{unique}"],
            metadata={"correlation_id": correlation_id, "updated": True},
        )

        operations.save(updated)

        persisted = operations.find_by_id(item_id)
        assert persisted is not None
        assert persisted.summary == updated.summary
        assert persisted.status == OperationalItemStatus.IN_PROGRESS
        assert persisted.owner_id == updated.owner_id
        assert persisted.confidence == pytest.approx(0.93)
        assert persisted.evidence == updated.evidence
        assert persisted.metadata["updated"] is True

        by_source = operations.find_by_source_event(
            "postgres-integration-test",
            source_event_id,
            OperationalItemType.TASK,
        )
        assert by_source is not None
        assert by_source.identifier.graph_id == item.identifier.graph_id

        correlated = operations.find_by_correlation(correlation_id)
        assert any(str(result.identifier.graph_id) == item_id for result in correlated)

        # Remove only the row created by this test.
    finally:
        with session_factory() as session:
            session.query(OperationalItemModel).filter(
                OperationalItemModel.id == item_id
            ).delete(synchronize_session=False)
            session.commit()


def test_activity_round_trip_deduplication_and_latest_state(
    postgres_repositories,
):
    _, activities, session_factory = postgres_repositories

    unique = uuid4().hex
    person_id = f"pg-test-person-{unique}"
    source_event_id = f"pg-test-activity-{unique}"
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    later = start + timedelta(minutes=5)

    first = ActivityEvent.create(
        person_id=person_id,
        person_name=f"PostgreSQL Test {unique}",
        activity_type=ActivityType.WORK_START,
        occurred_at=start,
        source=ActivitySource.SLACK,
        source_event_id=source_event_id,
        note="integration test work start",
    )
    second = ActivityEvent.create(
        person_id=person_id,
        person_name=f"PostgreSQL Test {unique}",
        activity_type=ActivityType.BREAK_START,
        occurred_at=later,
        source=ActivitySource.SLACK,
        source_event_id=f"{source_event_id}-later",
        break_type="lunch",
        note="integration test break start",
    )

    try:
        activities.save(first)
        activities.save(second)

        # Replaying the same source event should not insert a duplicate.
        duplicate = ActivityEvent.create(
            person_id=person_id,
            person_name=f"PostgreSQL Test {unique}",
            activity_type=ActivityType.WORK_START,
            occurred_at=start,
            source=ActivitySource.SLACK,
            source_event_id=source_event_id,
            note="duplicate replay",
        )
        activities.save(duplicate)

        # These repository calls use new database sessions.
        events = activities.find_for_person(person_id)
        assert len(events) == 2
        assert [event.source_event_id for event in events] == [
            source_event_id,
            f"{source_event_id}-later",
        ]

        latest = activities.find_latest_for_people()
        latest_for_person = {
            event.person_id: event for event in latest
        }[person_id]
        assert latest_for_person.activity_type == ActivityType.BREAK_START
        assert latest_for_person.source_event_id == f"{source_event_id}-later"

        with session_factory() as session:
            count = session.query(ActivityEventModel).filter(
                ActivityEventModel.person_id == person_id,
                ActivityEventModel.source_event_id == source_event_id,
            ).count()
        assert count == 1

    finally:
        with session_factory() as session:
            session.query(ActivityEventModel).filter(
                ActivityEventModel.person_id == person_id
            ).delete(synchronize_session=False)
            session.commit()


def test_operations_agent_postgres_persistence_for_task_decision_and_risk(
    postgres_repositories,
):
    """
    Test TASK, DECISION, and RISK creation through OperationsAgent
    and verify their persistence and retrieval from PostgreSQL.
    """
    operations, _, session_factory = postgres_repositories
    op_service = OperationalItemService(operations)
    agent = OperationsAgent(
        repository=operations,
        operational_item_service=op_service,
    )

    unique = uuid4().hex
    corr_id = f"pg-agent-corr-{unique}"
    created_ids: list[str] = []

    try:
        # 1. TASK creation through OperationsAgent
        task_due = datetime.now(timezone.utc) + timedelta(days=3)
        task_obs = Observation(
            observation_type=ObservationType.TASK,
            summary=f"Implement PostgreSQL data layer {unique}",
            evidence=[f"slack-msg-task-{unique}"],
            confidence=0.92,
            metadata={
                "assignee": f"dev-{unique}",
                "assignee_name": "Lead Engineer",
                "priority": "high",
                "due_at": task_due.isoformat(),
            },
        )
        task_event = OrganizationEvent(
            event_type=OrganizationEventType.TASK_CREATED,
            summary=f"Implement PostgreSQL data layer {unique}",
            observations=[task_obs],
            confidence=0.92,
        )
        task_res = agent.process_event(
            task_event,
            source_type="slack",
            source_event_id=f"evt-task-{unique}",
            correlation_id=corr_id,
        )

        assert task_res.operation == "created"
        assert task_res.status == OperationalItemStatus.OPEN
        assert task_res.affected_item_id is not None
        task_id = task_res.affected_item_id
        created_ids.append(task_id)

        # Retrieve and verify TASK from PostgreSQL
        retrieved_task = operations.find_by_id(task_id)
        assert retrieved_task is not None
        assert retrieved_task.item_type == OperationalItemType.TASK
        assert retrieved_task.summary == f"Implement PostgreSQL data layer {unique}"
        assert retrieved_task.status == OperationalItemStatus.OPEN
        assert retrieved_task.priority == OperationalItemPriority.HIGH
        assert retrieved_task.owner_id == f"dev-{unique}"
        assert retrieved_task.owner_name == "Lead Engineer"
        assert retrieved_task.source_event_id == f"evt-task-{unique}"
        assert retrieved_task.source_type == "slack"
        assert retrieved_task.evidence == [f"slack-msg-task-{unique}"]
        assert retrieved_task.metadata.get("correlation_id") == corr_id

        # 2. DECISION creation through OperationsAgent
        decision_obs = Observation(
            observation_type=ObservationType.DECISION,
            summary=f"Adopt SQLAlchemy 2.0 with psycopg driver {unique}",
            evidence=[f"slack-msg-decision-{unique}"],
            confidence=0.96,
            metadata={
                "owner_id": f"architect-{unique}",
                "owner_name": "Chief Architect",
                "priority": "high",
                "status": "accepted",
            },
        )
        decision_event = OrganizationEvent(
            event_type=OrganizationEventType.DECISION_MADE,
            summary=f"Adopt SQLAlchemy 2.0 with psycopg driver {unique}",
            observations=[decision_obs],
            confidence=0.96,
        )
        decision_res = agent.process_event(
            decision_event,
            source_type="slack",
            source_event_id=f"evt-decision-{unique}",
            correlation_id=corr_id,
        )

        assert decision_res.operation == "created"
        assert decision_res.status == OperationalItemStatus.ACCEPTED
        assert decision_res.affected_item_id is not None
        decision_id = decision_res.affected_item_id
        created_ids.append(decision_id)

        # Retrieve and verify DECISION from PostgreSQL
        retrieved_decision = operations.find_by_id(decision_id)
        assert retrieved_decision is not None
        assert retrieved_decision.item_type == OperationalItemType.DECISION
        assert retrieved_decision.summary == f"Adopt SQLAlchemy 2.0 with psycopg driver {unique}"
        assert retrieved_decision.status == OperationalItemStatus.ACCEPTED
        assert retrieved_decision.priority == OperationalItemPriority.HIGH
        assert retrieved_decision.owner_id == f"architect-{unique}"
        assert retrieved_decision.owner_name == "Chief Architect"
        assert retrieved_decision.source_event_id == f"evt-decision-{unique}"
        assert retrieved_decision.evidence == [f"slack-msg-decision-{unique}"]

        # 3. RISK creation through OperationsAgent
        risk_obs = Observation(
            observation_type=ObservationType.RISK,
            summary=f"Database connection pool exhaustion under load {unique}",
            evidence=[f"slack-msg-risk-{unique}"],
            confidence=0.89,
            metadata={
                "owner_id": f"sre-{unique}",
                "owner_name": "SRE Lead",
                "priority": "critical",
            },
        )
        risk_event = OrganizationEvent(
            event_type=OrganizationEventType.RISK_IDENTIFIED,
            summary=f"Database connection pool exhaustion under load {unique}",
            observations=[risk_obs],
            confidence=0.89,
        )
        risk_res = agent.process_event(
            risk_event,
            source_type="slack",
            source_event_id=f"evt-risk-{unique}",
            correlation_id=corr_id,
        )

        assert risk_res.operation == "created"
        assert risk_res.status == OperationalItemStatus.OPEN
        assert risk_res.affected_item_id is not None
        risk_id = risk_res.affected_item_id
        created_ids.append(risk_id)

        # Retrieve and verify RISK from PostgreSQL
        retrieved_risk = operations.find_by_id(risk_id)
        assert retrieved_risk is not None
        assert retrieved_risk.item_type == OperationalItemType.RISK
        assert retrieved_risk.summary == f"Database connection pool exhaustion under load {unique}"
        assert retrieved_risk.status == OperationalItemStatus.OPEN
        assert retrieved_risk.priority == OperationalItemPriority.CRITICAL
        assert retrieved_risk.owner_id == f"sre-{unique}"
        assert retrieved_risk.owner_name == "SRE Lead"
        assert retrieved_risk.source_event_id == f"evt-risk-{unique}"
        assert retrieved_risk.evidence == [f"slack-msg-risk-{unique}"]

        # Verify all 3 item types can be retrieved by correlation from PostgreSQL
        correlated_items = operations.find_by_correlation(corr_id)
        assert len(correlated_items) == 3
        types_in_db = {item.item_type for item in correlated_items}
        assert types_in_db == {
            OperationalItemType.TASK,
            OperationalItemType.DECISION,
            OperationalItemType.RISK,
        }

    finally:
        with session_factory() as session:
            session.query(OperationalItemModel).filter(
                OperationalItemModel.id.in_(created_ids)
            ).delete(synchronize_session=False)
            session.commit()


def test_activity_service_postgres_recording_and_retrieval(
    postgres_repositories,
):
    """
    Test activity recording and retrieval through ActivityService,
    including date filtering, name lookup, duplicate-event handling,
    and latest-state retrieval from PostgreSQL.
    """
    _, activities, session_factory = postgres_repositories
    calculator = AttendanceCalculator()
    activity_service = ActivityService(
        repository=activities,
        attendance_calculator=calculator,
    )

    unique = uuid4().hex
    person_1 = f"pg-person-alice-{unique}"
    person_2 = f"pg-person-bob-{unique}"
    person_3 = f"pg-person-charlie-{unique}"
    name_1 = f"Alice Walker {unique}"
    name_2 = f"Bob Martin {unique}"
    name_3 = f"Charlie Davis {unique}"

    base_time = datetime.now(timezone.utc) - timedelta(hours=4)
    t1 = base_time + timedelta(minutes=10)
    t2 = base_time + timedelta(minutes=60)
    t3 = base_time + timedelta(minutes=110)
    t4 = base_time + timedelta(minutes=160)

    try:
        # 1. Activity recording through ActivityService
        # Person 1 (Alice): starts work, goes on break, resumes work
        activity_service.record(
            person_id=person_1,
            person_name=name_1,
            activity_type=ActivityType.WORK_START,
            occurred_at=t1,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-a1-{unique}",
            note="alice morning login",
        )
        activity_service.record(
            person_id=person_1,
            person_name=name_1,
            activity_type=ActivityType.BREAK_START,
            occurred_at=t2,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-a2-{unique}",
            break_type="lunch",
            note="alice lunch start",
        )
        activity_service.record(
            person_id=person_1,
            person_name=name_1,
            activity_type=ActivityType.BREAK_END,
            occurred_at=t3,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-a3-{unique}",
            note="alice lunch end",
        )

        # Person 2 (Bob): starts work, goes on break (currently on break)
        activity_service.record(
            person_id=person_2,
            person_name=name_2,
            activity_type=ActivityType.WORK_START,
            occurred_at=t1,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-b1-{unique}",
            note="bob morning start",
        )
        activity_service.record(
            person_id=person_2,
            person_name=name_2,
            activity_type=ActivityType.BREAK_START,
            occurred_at=t3,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-b2-{unique}",
            break_type="coffee",
            note="bob coffee break",
        )

        # Person 3 (Charlie): starts work, ends work (currently off work)
        activity_service.record(
            person_id=person_3,
            person_name=name_3,
            activity_type=ActivityType.WORK_START,
            occurred_at=t1,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-c1-{unique}",
            note="charlie start shift",
        )
        activity_service.record(
            person_id=person_3,
            person_name=name_3,
            activity_type=ActivityType.WORK_END,
            occurred_at=t4,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-c2-{unique}",
            note="charlie end shift",
        )

        # 2. Date filtering
        # Full range captures all 3 events for Person 1
        all_events_p1 = activity_service.find_for_person(
            person_1,
            start=t1 - timedelta(minutes=5),
            end=t3 + timedelta(minutes=5),
        )
        assert len(all_events_p1) == 3
        assert [e.activity_type for e in all_events_p1] == [
            ActivityType.WORK_START,
            ActivityType.BREAK_START,
            ActivityType.BREAK_END,
        ]

        # Narrow range captures only the middle event (BREAK_START)
        windowed = activity_service.find_for_person(
            person_1,
            start=t2 - timedelta(minutes=10),
            end=t2 + timedelta(minutes=10),
        )
        assert len(windowed) == 1
        assert windowed[0].activity_type == ActivityType.BREAK_START
        assert windowed[0].break_type == "lunch"

        # Out-of-bounds range returns empty list
        empty_window = activity_service.find_for_person(
            person_1,
            start=t4 + timedelta(hours=1),
            end=t4 + timedelta(hours=2),
        )
        assert empty_window == []

        # 3. Name lookup (case-insensitive)
        matched_alice = activity_service.find_people_by_name(name_1)
        assert len(matched_alice) == 1
        assert matched_alice[0].person_id == person_1
        assert matched_alice[0].person_name == name_1

        matched_alice_lower = activity_service.find_for_person_by_name(name_1.lower())
        assert len(matched_alice_lower) == 1
        assert matched_alice_lower[0].person_id == person_1

        matched_bob = activity_service.find_people_by_name(name_2)
        assert len(matched_bob) == 1
        assert matched_bob[0].person_id == person_2

        non_existent = activity_service.find_people_by_name(f"Non Existent Person {unique}")
        assert non_existent == []

        # 4. Duplicate-event handling
        # Recording the exact same source event must be idempotent
        activity_service.record(
            person_id=person_1,
            person_name=name_1,
            activity_type=ActivityType.WORK_START,
            occurred_at=t1,
            source=ActivitySource.SLACK,
            source_event_id=f"evt-a1-{unique}",
            note="alice morning login duplicate attempt",
        )

        events_after_duplicate = activity_service.find_for_person(person_1)
        assert len(events_after_duplicate) == 3

        with session_factory() as session:
            count = session.query(ActivityEventModel).filter(
                ActivityEventModel.person_id == person_1,
                ActivityEventModel.source_event_id == f"evt-a1-{unique}",
            ).count()
        assert count == 1

        # 5. Latest-state retrieval
        # Alice: last event is BREAK_END -> working
        # Bob: last event is BREAK_START -> on break
        # Charlie: last event is WORK_END -> off work
        working_by_id = {e.person_id: e for e in activity_service.find_currently_working()}
        on_break_by_id = {e.person_id: e for e in activity_service.find_currently_on_break()}
        off_work_by_id = {e.person_id: e for e in activity_service.find_currently_off_work()}

        assert person_1 in working_by_id
        assert working_by_id[person_1].activity_type == ActivityType.BREAK_END

        assert person_2 in on_break_by_id
        assert on_break_by_id[person_2].activity_type == ActivityType.BREAK_START

        assert person_3 in off_work_by_id
        assert off_work_by_id[person_3].activity_type == ActivityType.WORK_END

    finally:
        with session_factory() as session:
            session.query(ActivityEventModel).filter(
                ActivityEventModel.person_id.in_([person_1, person_2, person_3])
            ).delete(synchronize_session=False)
            session.commit()
