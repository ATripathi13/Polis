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
