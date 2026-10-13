import pytest

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)

from domain.observation import (
    Observation,
    ObservationType,
)


def test_create_organization_event():

    observation = Observation(
        observation_type=ObservationType.TASK,
        summary="John will deploy tomorrow.",
    )

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Deployment task created.",
        observations=[observation],
    )

    assert (
        event.event_type
        == OrganizationEventType.TASK_CREATED
    )

    assert len(event.observations) == 1

    assert (
        event.observations[0].observation_type
        == ObservationType.TASK
    )


def test_organization_event_rejects_empty_summary():

    with pytest.raises(
        ValueError,
        match="summary must not be empty",
    ):
        OrganizationEvent(
            event_type=OrganizationEventType.TASK_CREATED,
            summary="   ",
        )


def test_organization_event_rejects_invalid_confidence():

    with pytest.raises(
        ValueError,
        match="confidence must be between 0.0 and 1.0",
    ):
        OrganizationEvent(
            event_type=OrganizationEventType.TASK_CREATED,
            summary="Deployment task created.",
            confidence=1.5,
        )

    with pytest.raises(
        ValueError,
        match="confidence must be between 0.0 and 1.0",
    ):
        OrganizationEvent(
            event_type=OrganizationEventType.TASK_CREATED,
            summary="Deployment task created.",
            confidence=-0.1,
        )


def test_organization_event_preserves_temporal_and_correlation_metadata():
    from datetime import datetime, timezone
    from domain.common.identifier import Identifier

    now = datetime.now(timezone.utc)
    corr_id = Identifier(business_id="thread-abc")

    observation = Observation(
        observation_type=ObservationType.TASK,
        summary="John will deploy tomorrow.",
        evidence=["slack-ts-123"],
        correlation_id=corr_id,
        occurred_at=now,
    )

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Deployment task created.",
        observations=[observation],
        correlation_id=corr_id,
        occurred_at=now,
    )

    assert event.correlation_id == corr_id
    assert event.occurred_at == now
    assert event.observations[0].evidence == ["slack-ts-123"]


def test_organization_event_accepts_string_correlation_id():
    from domain.common.identifier import Identifier

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Deployment task created.",
        correlation_id="thread-xyz",
    )

    assert isinstance(event.correlation_id, Identifier)
    assert event.correlation_id.business_id == "thread-xyz"
