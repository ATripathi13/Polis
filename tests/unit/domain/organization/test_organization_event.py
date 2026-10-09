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
