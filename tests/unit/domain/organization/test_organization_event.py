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