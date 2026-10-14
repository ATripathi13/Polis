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
