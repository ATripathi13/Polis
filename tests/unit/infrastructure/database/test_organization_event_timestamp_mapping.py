from datetime import datetime, timezone
from types import SimpleNamespace

from infrastructure.database.organization_event_repository import (
    PostgreSQLOrganizationEventRepository,
)


def test_to_domain_restores_event_and_observation_timestamps():
    source_timestamp = datetime(
        2024, 4, 5, 19, 34, 38, 123456, tzinfo=timezone.utc
    )
    record = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000001",
        event_type="task_created",
        summary="Prepare deployment report",
        observations=[
            {
                "observation_type": "task",
                "summary": "Prepare deployment report",
                "confidence": 0.9,
                "evidence": ["slack-event-1"],
                "correlation_id": None,
                "occurred_at": source_timestamp.isoformat(),
            }
        ],
        confidence=0.9,
        correlation_id=None,
        correlation_business_id=None,
        occurred_at=source_timestamp,
    )

    event = PostgreSQLOrganizationEventRepository._to_domain(record)

    assert event.occurred_at == source_timestamp
    assert event.observations[0].occurred_at == source_timestamp
    assert event.observations[0].evidence == ["slack-event-1"]


def test_to_domain_uses_observation_timestamp_when_event_timestamp_missing():
    source_timestamp = datetime(
        2024, 4, 5, 19, 34, 38, 123456, tzinfo=timezone.utc
    )
    record = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000002",
        event_type="task_created",
        summary="Prepare deployment report",
        observations=[
            {
                "observation_type": "task",
                "summary": "Prepare deployment report",
                "confidence": 0.9,
                "evidence": ["slack-event-2"],
                "correlation_id": None,
                "occurred_at": source_timestamp.isoformat(),
            }
        ],
        confidence=0.9,
        correlation_id=None,
        correlation_business_id=None,
        occurred_at=None,
    )

    event = PostgreSQLOrganizationEventRepository._to_domain(record)

    assert event.occurred_at == source_timestamp
    assert event.observations[0].occurred_at == source_timestamp


def test_save_serializes_event_and_observation_timestamps(monkeypatch):
    from domain.observation import Observation, ObservationType
    from domain.organization import OrganizationEvent, OrganizationEventType
    from infrastructure.database import organization_event_repository as repository_module

    source_timestamp = datetime(
        2024, 4, 5, 19, 34, 38, 123456, tzinfo=timezone.utc
    )

    observation = Observation(
        observation_type=ObservationType.TASK,
        summary="Prepare deployment report",
        confidence=0.9,
        evidence=["slack-event-3"],
        occurred_at=source_timestamp,
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Prepare deployment report",
        observations=[observation],
        confidence=0.9,
        occurred_at=source_timestamp,
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeSession:
        def __init__(self):
            self.added = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def query(self, *args, **kwargs):
            return FakeQuery()

        def add(self, record):
            self.added = record

        def commit(self):
            pass

    fake_session = FakeSession()
    monkeypatch.setattr(
        repository_module,
        "SessionLocal",
        lambda: fake_session,
    )

    PostgreSQLOrganizationEventRepository().save(
        event,
        source_type="slack",
        source_event_id="slack-event-3",
    )

    assert fake_session.added is not None
    assert fake_session.added.occurred_at == source_timestamp
    assert (
        fake_session.added.observations[0]["occurred_at"]
        == source_timestamp.isoformat()
    )


def test_find_by_correlation_queries_business_id(monkeypatch):
    from domain.common.identifier import Identifier
    from infrastructure.database import organization_event_repository as repository_module
    from infrastructure.database.models import OrganizationEventModel

    correlation = Identifier(business_id="meeting-100")
    record = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000010",
        event_type="task_created",
        summary="Prepare deployment report",
        observations=[],
        confidence=0.9,
        correlation_id=str(correlation.graph_id),
        correlation_business_id="meeting-100",
        occurred_at=None,
        created_at=datetime(2024, 4, 5, tzinfo=timezone.utc),
    )

    class FakeQuery:
        def __init__(self):
            self.filters = []
            self.ordered_by = None

        def filter(self, *criteria):
            self.filters.extend(criteria)
            return self

        def order_by(self, expression):
            self.ordered_by = expression
            return self

        def all(self):
            return [record]

    class FakeSession:
        def __init__(self):
            self.query_instance = FakeQuery()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def query(self, model):
            assert model is OrganizationEventModel
            return self.query_instance

    fake_session = FakeSession()
    monkeypatch.setattr(
        repository_module,
        "SessionLocal",
        lambda: fake_session,
    )

    events = PostgreSQLOrganizationEventRepository().find_by_correlation(
        correlation
    )

    assert len(events) == 1
    assert events[0].summary == "Prepare deployment report"
    assert len(fake_session.query_instance.filters) == 1


def test_find_by_correlation_falls_back_to_graph_id(monkeypatch):
    from uuid import uuid4

    from domain.common.identifier import Identifier
    from infrastructure.database import organization_event_repository as repository_module
    from infrastructure.database.models import OrganizationEventModel

    correlation = Identifier(graph_id=uuid4())
    record = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000011",
        event_type="task_created",
        summary="Graph-linked event",
        observations=[],
        confidence=0.9,
        correlation_id=str(correlation.graph_id),
        correlation_business_id=None,
        occurred_at=None,
        created_at=datetime(2024, 4, 5, tzinfo=timezone.utc),
    )

    class FakeQuery:
        def __init__(self):
            self.filters = []

        def filter(self, *criteria):
            self.filters.extend(criteria)
            return self

        def order_by(self, expression):
            return self

        def all(self):
            return [record]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def query(self, model):
            assert model is OrganizationEventModel
            return query

    query = FakeQuery()
    monkeypatch.setattr(repository_module, "SessionLocal", FakeSession)

    events = PostgreSQLOrganizationEventRepository().find_by_correlation(
        correlation
    )

    assert len(events) == 1
    assert events[0].summary == "Graph-linked event"
    assert len(query.filters) == 1


def test_find_by_correlation_accepts_plain_string(monkeypatch):
    from infrastructure.database import organization_event_repository as repository_module
    from infrastructure.database.models import OrganizationEventModel

    record = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000012",
        event_type="task_created",
        summary="Business-linked event",
        observations=[],
        confidence=0.9,
        correlation_id=None,
        correlation_business_id="meeting-plain-string",
        occurred_at=None,
        created_at=datetime(2024, 4, 5, tzinfo=timezone.utc),
    )

    class FakeQuery:
        def __init__(self):
            self.filters = []

        def filter(self, *criteria):
            self.filters.extend(criteria)
            return self

        def order_by(self, expression):
            return self

        def all(self):
            return [record]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def query(self, model):
            assert model is OrganizationEventModel
            return query

    query = FakeQuery()
    monkeypatch.setattr(repository_module, "SessionLocal", FakeSession)

    events = PostgreSQLOrganizationEventRepository().find_by_correlation(
        "meeting-plain-string"
    )

    assert len(events) == 1
    assert events[0].summary == "Business-linked event"
    assert len(query.filters) == 1


def test_save_preserves_observation_correlation_identity(monkeypatch):
    from uuid import uuid4

    from domain.common.identifier import Identifier
    from domain.observation import Observation, ObservationType
    from domain.organization import OrganizationEvent, OrganizationEventType
    from infrastructure.database import organization_event_repository as repository_module

    correlation = Identifier(graph_id=uuid4())
    observation = Observation(
        observation_type=ObservationType.TASK,
        summary="Prepare deployment report",
        correlation_id=correlation,
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Prepare deployment report",
        observations=[observation],
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeSession:
        def __init__(self):
            self.added = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def query(self, *args, **kwargs):
            return FakeQuery()

        def add(self, record):
            self.added = record

        def commit(self):
            pass

    fake_session = FakeSession()
    monkeypatch.setattr(
        repository_module,
        "SessionLocal",
        lambda: fake_session,
    )

    PostgreSQLOrganizationEventRepository().save(
        event,
        source_type="slack",
        source_event_id="correlation-identity-test",
    )

    saved_observation = fake_session.added.observations[0]
    assert saved_observation["correlation_id"] == str(correlation.graph_id)
    assert saved_observation["correlation_graph_id"] == str(correlation.graph_id)
    assert saved_observation["correlation_business_id"] is None

    record = SimpleNamespace(
        event_type=event.event_type.value,
        summary=event.summary,
        observations=fake_session.added.observations,
        confidence=event.confidence,
        correlation_id=None,
        correlation_business_id=None,
        occurred_at=None,
    )
    restored = PostgreSQLOrganizationEventRepository._to_domain(record)
    restored_correlation = restored.observations[0].correlation_id

    assert restored_correlation is not None
    assert restored_correlation.graph_id == correlation.graph_id
    assert restored_correlation.business_id == ""


def test_to_domain_restores_legacy_observation_correlation_id():
    from uuid import UUID

    graph_id = "00000000-0000-4000-8000-000000000011"
    record = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000012",
        event_type="task_created",
        summary="Legacy graph correlation",
        observations=[
            {
                "observation_type": "task",
                "summary": "Legacy graph correlation",
                "confidence": 0.9,
                "evidence": [],
                "correlation_id": graph_id,
            },
            {
                "observation_type": "task",
                "summary": "Legacy business correlation",
                "confidence": 0.9,
                "evidence": [],
                "correlation_id": "legacy-business-123",
            },
        ],
        confidence=0.9,
        correlation_id=None,
        correlation_business_id=None,
        occurred_at=None,
    )

    event = PostgreSQLOrganizationEventRepository._to_domain(record)

    graph_correlation = event.observations[0].correlation_id
    business_correlation = event.observations[1].correlation_id

    assert graph_correlation is not None
    assert graph_correlation.graph_id == UUID(graph_id)
    assert graph_correlation.business_id == ""
    assert business_correlation is not None
    assert business_correlation.business_id == "legacy-business-123"


def test_save_ignores_concurrent_duplicate_event_conflict(monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from domain.organization import OrganizationEvent, OrganizationEventType
    from infrastructure.database import organization_event_repository as repository_module

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Prepare deployment report",
        observations=[],
        confidence=0.9,
    )

    original_error = SimpleNamespace(
        diag=SimpleNamespace(
            constraint_name="uq_organization_events_source_event_type"
        )
    )
    duplicate_error = IntegrityError(
        "duplicate organization event",
        {},
        original_error,
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def query(self, *args, **kwargs):
            return FakeQuery()

        def add(self, record):
            pass

        def commit(self):
            raise duplicate_error

        def rollback(self):
            pass

    monkeypatch.setattr(
        repository_module,
        "SessionLocal",
        lambda: FakeSession(),
    )

    PostgreSQLOrganizationEventRepository().save(
        event,
        source_type="slack",
        source_event_id="concurrent-duplicate-event",
    )

def test_save_reraises_unrelated_integrity_error(monkeypatch):
    import pytest
    from sqlalchemy.exc import IntegrityError
    from domain.organization import OrganizationEvent, OrganizationEventType
    from infrastructure.database import organization_event_repository as repository_module

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Prepare deployment report",
        observations=[],
        confidence=0.9,
    )

    original_error = SimpleNamespace(
        diag=SimpleNamespace(constraint_name="some_other_constraint")
    )
    integrity_error = IntegrityError("unrelated constraint", {}, original_error)

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeSession:
        def __init__(self):
            self.rollback_called = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def query(self, *args, **kwargs):
            return FakeQuery()

        def add(self, record):
            pass

        def commit(self):
            raise integrity_error

        def rollback(self):
            self.rollback_called = True

    fake_session = FakeSession()
    monkeypatch.setattr(
        repository_module,
        "SessionLocal",
        lambda: fake_session,
    )

    with pytest.raises(IntegrityError) as raised:
        PostgreSQLOrganizationEventRepository().save(
            event,
            source_type="slack",
            source_event_id="unrelated-integrity-error",
        )

    assert raised.value is integrity_error
    assert fake_session.rollback_called
