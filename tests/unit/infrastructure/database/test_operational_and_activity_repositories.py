
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

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
from infrastructure.database import (
    operational_item_repository as operational_module,
)
from infrastructure.database.activity_repository import (
    PostgreSQLActivityRepository,
)
from infrastructure.database.operational_item_repository import (
    PostgreSQLOperationalItemRepository,
)
from infrastructure.database.models import (
    ActivityEventModel,
    OperationalItemModel,
)


def make_operational_item(item_type):
    return OperationalItem(
        identifier=Identifier(),
        item_type=item_type,
        summary=f"Test {item_type.value}",
        status=OperationalItemStatus.IN_PROGRESS,
        priority=OperationalItemPriority.HIGH,
        owner_id="person-1",
        owner_name="Test Person",
        due_at=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
        source_event_id=f"event-{item_type.value}",
        source_type="slack",
        confidence=0.85,
        evidence=["message-1", "message-2"],
        metadata={"correlation_id": "meeting-1", "test": True},
    )


def make_operational_record(
    item_type=OperationalItemType.TASK,
    owner_id="person-1",
    owner_name="Test Person",
    status=OperationalItemStatus.OPEN,
    due_at=None,
):
    item = make_operational_item(item_type)
    return OperationalItemModel(
        id=str(item.identifier.graph_id),
        item_type=item_type.value,
        summary=f"Test {item_type.value}",
        status=status.value,
        priority=item.priority.value,
        owner_id=owner_id,
        owner_name=owner_name,
        due_at=due_at if due_at is not None else item.due_at,
        source_event_id=item.source_event_id,
        source_type=item.source_type,
        confidence=item.confidence,
        evidence=list(item.evidence),
        metadata_=dict(item.metadata),
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
    )


def compile_filter(expr) -> str:
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def make_activity(
    person_id,
    activity_type,
    occurred_at,
    source_event_id,
    person_name="Test Person",
):
    return ActivityEvent.create(
        person_id=person_id,
        person_name=person_name,
        activity_type=activity_type,
        occurred_at=occurred_at,
        source=ActivitySource.SLACK,
        source_event_id=source_event_id,
        break_type="lunch" if activity_type == ActivityType.BREAK_START else None,
        note=f"note-{source_event_id}",
    )


class FakeQuery:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.filters = []
        self.ordering = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *expressions):
        self.ordering.extend(expressions)
        return self

    def first(self):
        return self.records[0] if self.records else None

    def all(self):
        return list(self.records)


class FakeSession:
    def __init__(self, records=None):
        self.query_instance = FakeQuery(records)
        self.added = []
        self.commits = 0
        self.refreshed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def query(self, model):
        self.queried_model = model
        return self.query_instance

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.commits += 1

    def refresh(self, record):
        self.refreshed.append(record)


def test_operational_item_save_persists_all_item_types(monkeypatch):
    for item_type in (
        OperationalItemType.TASK,
        OperationalItemType.DECISION,
        OperationalItemType.RISK,
    ):
        item = make_operational_item(item_type)
        session = FakeSession()
        monkeypatch.setattr(
            operational_module,
            "SessionLocal",
            lambda session=session: session,
        )

        saved = PostgreSQLOperationalItemRepository().save(item)

        assert len(session.added) == 1
        assert session.commits == 1

        record = session.added[0]
        assert record.id == str(item.identifier.graph_id)
        assert record.item_type == item_type.value
        assert record.summary == item.summary
        assert record.status == item.status.value
        assert record.priority == item.priority.value
        assert record.owner_id == item.owner_id
        assert record.owner_name == item.owner_name
        assert record.source_event_id == item.source_event_id
        assert record.source_type == item.source_type
        assert record.evidence == item.evidence
        assert record.metadata_ == item.metadata

        assert saved.item_type == item_type
        assert saved.summary == item.summary
        assert saved.evidence == item.evidence
        assert saved.metadata == item.metadata


def test_operational_item_find_by_id_reconstructs_domain_item(monkeypatch):
    item = make_operational_item(OperationalItemType.TASK)
    record = OperationalItemModel(
        id=str(item.identifier.graph_id),
        item_type=item.item_type.value,
        summary=item.summary,
        status=item.status.value,
        priority=item.priority.value,
        owner_id=item.owner_id,
        owner_name=item.owner_name,
        due_at=item.due_at,
        source_event_id=item.source_event_id,
        source_type=item.source_type,
        confidence=item.confidence,
        evidence=item.evidence,
        metadata_=item.metadata,
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    result = PostgreSQLOperationalItemRepository().find_by_id(
        str(item.identifier.graph_id)
    )

    assert result is not None
    assert result.identifier.graph_id == item.identifier.graph_id
    assert result.item_type == item.item_type
    assert result.status == item.status
    assert result.priority == item.priority
    assert result.owner_id == item.owner_id
    assert result.due_at == item.due_at
    assert result.evidence == item.evidence
    assert result.metadata == item.metadata


def test_operational_item_find_by_correlation_filters_item_type(monkeypatch):
    item = make_operational_item(OperationalItemType.RISK)
    record = SimpleNamespace(
        id=str(item.identifier.graph_id),
        item_type=item.item_type.value,
        summary=item.summary,
        status=item.status.value,
        priority=item.priority.value,
        owner_id=item.owner_id,
        owner_name=item.owner_name,
        due_at=item.due_at,
        source_event_id=item.source_event_id,
        source_type=item.source_type,
        confidence=item.confidence,
        evidence=item.evidence,
        metadata_=item.metadata,
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    results = PostgreSQLOperationalItemRepository().find_by_correlation(
        "meeting-1",
        item_type=OperationalItemType.RISK,
    )

    assert len(results) == 1
    assert results[0].item_type == OperationalItemType.RISK
    assert len(session.query_instance.filters) == 2


def test_find_open_for_owner_or_name_filters_and_ordering(monkeypatch):
    record = make_operational_record(
        item_type=OperationalItemType.TASK,
        owner_id="user-123",
        owner_name="Alice Smith",
        status=OperationalItemStatus.OPEN,
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    results = PostgreSQLOperationalItemRepository().find_open_for_owner_or_name(
        owner_id="user-123",
        owner_name="Alice Smith",
        item_type=OperationalItemType.TASK,
    )

    assert len(results) == 1
    assert isinstance(results[0], OperationalItem)
    assert results[0].identifier.graph_id == UUID(record.id)
    assert results[0].item_type == OperationalItemType.TASK
    assert results[0].summary == record.summary
    assert results[0].status == OperationalItemStatus.OPEN
    assert results[0].owner_id == "user-123"
    assert results[0].owner_name == "Alice Smith"

    compiled_filters = [compile_filter(f) for f in session.query_instance.filters]
    assert "operational_items.status IN ('open', 'in_progress')" in compiled_filters
    assert (
        "operational_items.owner_id = 'user-123' OR operational_items.owner_name = 'Alice Smith'"
        in compiled_filters
    )
    assert "operational_items.item_type = 'task'" in compiled_filters
    assert len(session.query_instance.filters) == 3

    assert len(session.query_instance.ordering) == 1
    assert str(session.query_instance.ordering[0]) == "operational_items.created_at DESC"


def test_find_open_for_owner_or_name_without_item_type_filter(monkeypatch):
    record = make_operational_record(
        item_type=OperationalItemType.DECISION,
        owner_id="user-123",
        owner_name="Alice Smith",
        status=OperationalItemStatus.IN_PROGRESS,
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    results = PostgreSQLOperationalItemRepository().find_open_for_owner_or_name(
        owner_id="user-123",
        owner_name="Alice Smith",
        item_type=None,
    )

    assert len(results) == 1
    assert isinstance(results[0], OperationalItem)
    assert results[0].item_type == OperationalItemType.DECISION

    compiled_filters = [compile_filter(f) for f in session.query_instance.filters]
    assert "operational_items.status IN ('open', 'in_progress')" in compiled_filters
    assert (
        "operational_items.owner_id = 'user-123' OR operational_items.owner_name = 'Alice Smith'"
        in compiled_filters
    )
    assert not any("operational_items.item_type" in c for c in compiled_filters)
    assert len(session.query_instance.filters) == 2

    assert len(session.query_instance.ordering) == 1
    assert str(session.query_instance.ordering[0]) == "operational_items.created_at DESC"


def test_find_overdue_for_owner_or_name_filters_and_ordering(monkeypatch):
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    due_at = now - timedelta(days=2)
    record = make_operational_record(
        item_type=OperationalItemType.TASK,
        owner_id="user-456",
        owner_name="Bob Jones",
        status=OperationalItemStatus.OPEN,
        due_at=due_at,
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    results = PostgreSQLOperationalItemRepository().find_overdue_for_owner_or_name(
        now,
        owner_id="user-456",
        owner_name="Bob Jones",
    )

    assert len(results) == 1
    assert isinstance(results[0], OperationalItem)
    assert results[0].due_at == due_at
    assert results[0].owner_id == "user-456"

    compiled_filters = [compile_filter(f) for f in session.query_instance.filters]
    assert "operational_items.due_at IS NOT NULL" in compiled_filters
    assert any("operational_items.due_at < '2026-10-20 12:00:00" in c for c in compiled_filters)
    assert "operational_items.status IN ('open', 'in_progress')" in compiled_filters
    assert (
        "operational_items.owner_id = 'user-456' OR operational_items.owner_name = 'Bob Jones'"
        in compiled_filters
    )
    assert len(session.query_instance.filters) == 4

    assert len(session.query_instance.ordering) == 1
    assert str(session.query_instance.ordering[0]) == "operational_items.due_at ASC"


def test_find_due_between_for_owner_or_name_filters_and_ordering(monkeypatch):
    start = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    due_at = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
    record = make_operational_record(
        item_type=OperationalItemType.RISK,
        owner_id="user-789",
        owner_name="Charlie Brown",
        status=OperationalItemStatus.IN_PROGRESS,
        due_at=due_at,
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    results = PostgreSQLOperationalItemRepository().find_due_between_for_owner_or_name(
        start,
        end,
        owner_id="user-789",
        owner_name="Charlie Brown",
    )

    assert len(results) == 1
    assert isinstance(results[0], OperationalItem)
    assert results[0].due_at == due_at
    assert results[0].item_type == OperationalItemType.RISK

    compiled_filters = [compile_filter(f) for f in session.query_instance.filters]
    assert "operational_items.due_at IS NOT NULL" in compiled_filters
    assert any("operational_items.due_at >= '2026-10-10 00:00:00" in c for c in compiled_filters)
    assert any("operational_items.due_at <= '2026-10-20 00:00:00" in c for c in compiled_filters)
    assert "operational_items.status IN ('open', 'in_progress')" in compiled_filters
    assert (
        "operational_items.owner_id = 'user-789' OR operational_items.owner_name = 'Charlie Brown'"
        in compiled_filters
    )
    assert len(session.query_instance.filters) == 5

    assert len(session.query_instance.ordering) == 1
    assert str(session.query_instance.ordering[0]) == "operational_items.due_at ASC"


def test_find_due_between_for_owner_or_name_accepts_start_equal_end(monkeypatch):
    point = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    record = make_operational_record(
        due_at=point,
        owner_id="user-789",
        owner_name="Charlie Brown",
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    results = PostgreSQLOperationalItemRepository().find_due_between_for_owner_or_name(
        point,
        point,
        owner_id="user-789",
        owner_name="Charlie Brown",
    )

    assert len(results) == 1
    compiled_filters = [compile_filter(f) for f in session.query_instance.filters]
    assert any("operational_items.due_at >= '2026-10-15 12:00:00" in c for c in compiled_filters)
    assert any("operational_items.due_at <= '2026-10-15 12:00:00" in c for c in compiled_filters)


def test_find_due_between_for_owner_or_name_raises_value_error_before_session(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)

    session_called = False

    def fail_session():
        nonlocal session_called
        session_called = True
        raise AssertionError("SessionLocal should not be called when start > end")

    monkeypatch.setattr(operational_module, "SessionLocal", fail_session)

    with pytest.raises(ValueError, match="start.*must not be after end"):
        PostgreSQLOperationalItemRepository().find_due_between_for_owner_or_name(
            start,
            end,
            owner_id="user-789",
            owner_name="Charlie Brown",
        )

    assert not session_called


def test_activity_save_persists_event_and_deduplicates_source(monkeypatch):
    event = make_activity(
        "person-1",
        ActivityType.WORK_START,
        datetime(2026, 10, 21, 9, tzinfo=timezone.utc),
        "slack-event-1",
    )
    session = FakeSession()
    monkeypatch.setattr(
        activity_module,
        "SessionLocal",
        lambda: session,
    )

    PostgreSQLActivityRepository().save(event)

    assert len(session.added) == 1
    assert session.commits == 1

    record = session.added[0]
    assert record.id == str(event.identifier.graph_id)
    assert record.person_id == event.person_id
    assert record.person_name == event.person_name
    assert record.activity_type == event.activity_type.value
    assert record.occurred_at == event.occurred_at
    assert record.source == event.source.value
    assert record.source_event_id == event.source_event_id
    assert record.note == event.note

    # A matching source event is already present.
    existing = SimpleNamespace(
        id=str(event.identifier.graph_id),
        person_id=event.person_id,
        source_event_id=event.source_event_id,
    )
    duplicate_session = FakeSession([existing])
    monkeypatch.setattr(
        activity_module,
        "SessionLocal",
        lambda: duplicate_session,
    )

    PostgreSQLActivityRepository().save(event)

    assert duplicate_session.added == []
    assert duplicate_session.commits == 0


def test_activity_find_for_person_applies_time_bounds(monkeypatch):
    event = make_activity(
        "person-1",
        ActivityType.WORK_START,
        datetime(2026, 10, 21, 9, tzinfo=timezone.utc),
        "slack-event-2",
    )
    record = SimpleNamespace(
        id=str(event.identifier.graph_id),
        person_id=event.person_id,
        person_name=event.person_name,
        activity_type=event.activity_type.value,
        occurred_at=event.occurred_at,
        source=event.source.value,
        source_event_id=event.source_event_id,
        break_type=event.break_type,
        note=event.note,
        created_at=datetime(2026, 10, 21, 9, tzinfo=timezone.utc),
    )
    session = FakeSession([record])
    monkeypatch.setattr(
        activity_module,
        "SessionLocal",
        lambda: session,
    )

    start = event.occurred_at - timedelta(minutes=5)
    end = event.occurred_at + timedelta(minutes=5)

    results = PostgreSQLActivityRepository().find_for_person(
        "person-1",
        start=start,
        end=end,
    )

    assert len(results) == 1
    assert results[0].person_id == event.person_id
    assert results[0].activity_type == event.activity_type
    assert results[0].source_event_id == event.source_event_id
    assert results[0].note == event.note
    assert len(session.query_instance.filters) == 3


def test_latest_activity_is_selected_per_person(monkeypatch):
    older = make_activity(
        "person-1",
        ActivityType.WORK_START,
        datetime(2026, 10, 21, 9, tzinfo=timezone.utc),
        "slack-old",
    )
    newer = make_activity(
        "person-1",
        ActivityType.BREAK_START,
        datetime(2026, 10, 21, 11, tzinfo=timezone.utc),
        "slack-new",
    )
    another_person = make_activity(
        "person-2",
        ActivityType.WORK_START,
        datetime(2026, 10, 21, 10, tzinfo=timezone.utc),
        "slack-other",
        person_name="Another Person",
    )

    def as_record(event, created_at):
        return SimpleNamespace(
            id=str(event.identifier.graph_id),
            person_id=event.person_id,
            person_name=event.person_name,
            activity_type=event.activity_type.value,
            occurred_at=event.occurred_at,
            source=event.source.value,
            source_event_id=event.source_event_id,
            break_type=event.break_type,
            note=event.note,
            created_at=created_at,
        )

    records = [
        as_record(newer, datetime(2026, 10, 21, 11, tzinfo=timezone.utc)),
        as_record(another_person, datetime(2026, 10, 21, 10, tzinfo=timezone.utc)),
        as_record(older, datetime(2026, 10, 21, 9, tzinfo=timezone.utc)),
    ]
    session = FakeSession(records)
    monkeypatch.setattr(
        activity_module,
        "SessionLocal",
        lambda: session,
    )

    latest = PostgreSQLActivityRepository().find_latest_for_people()

    by_person = {event.person_id: event for event in latest}

    assert set(by_person) == {"person-1", "person-2"}
    assert by_person["person-1"].activity_type == ActivityType.BREAK_START
    assert by_person["person-1"].source_event_id == "slack-new"
    assert by_person["person-2"].source_event_id == "slack-other"


def test_operational_item_save_updates_existing_record(monkeypatch):
    item = make_operational_item(OperationalItemType.TASK)
    old_updated_at = datetime(2026, 10, 20, tzinfo=timezone.utc)

    record = OperationalItemModel(
        id=str(item.identifier.graph_id),
        item_type=item.item_type.value,
        summary="Old summary",
        status=OperationalItemStatus.OPEN.value,
        priority=OperationalItemPriority.LOW.value,
        owner_id="old-owner",
        owner_name="Old Owner",
        due_at=None,
        source_event_id=item.source_event_id,
        source_type=item.source_type,
        confidence=0.5,
        evidence=["old-evidence"],
        metadata_={"correlation_id": "old-correlation"},
        created_at=old_updated_at,
        updated_at=old_updated_at,
    )

    session = FakeSession([record])
    monkeypatch.setattr(
        operational_module,
        "SessionLocal",
        lambda: session,
    )

    saved = PostgreSQLOperationalItemRepository().save(item)

    assert session.added == []
    assert session.commits == 1
    assert session.refreshed == [record]

    assert record.summary == item.summary
    assert record.status == item.status.value
    assert record.priority == item.priority.value
    assert record.owner_id == item.owner_id
    assert record.owner_name == item.owner_name
    assert record.due_at == item.due_at
    assert record.confidence == item.confidence
    assert record.evidence == item.evidence
    assert record.metadata_ == item.metadata
    assert record.updated_at >= old_updated_at

    assert saved.identifier.graph_id == item.identifier.graph_id
    assert saved.summary == item.summary
    assert saved.status == item.status
    assert saved.priority == item.priority
    assert saved.owner_id == item.owner_id
    assert saved.evidence == item.evidence
    assert saved.metadata == item.metadata
