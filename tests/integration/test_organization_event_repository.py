from domain.observation import Observation, ObservationType
from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from infrastructure.database import (
    PostgreSQLOrganizationEventRepository,
)


def test_organization_event_repository_save_find_and_deduplicate():

    repository = PostgreSQLOrganizationEventRepository()

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Prepare deployment report",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Prepare deployment report",
                confidence=0.9,
                evidence=["slack-organization-event-test"],
            )
        ],
        confidence=0.9,
    )

    source_type = "slack"
    source_event_id = "slack-organization-event-test"

    repository.save(
        event,
        source_type=source_type,
        source_event_id=source_event_id,
    )

    found = repository.find_by_source_event(
        source_type,
        source_event_id,
        OrganizationEventType.TASK_CREATED,
    )

    assert found is not None
    assert found.event_type == OrganizationEventType.TASK_CREATED
    assert found.summary == "Prepare deployment report"
    assert found.confidence == 0.9
    assert len(found.observations) == 1
    assert found.observations[0].observation_type == ObservationType.TASK
    assert found.observations[0].evidence == [
        "slack-organization-event-test"
    ]

    repository.save(
        event,
        source_type=source_type,
        source_event_id=source_event_id,
    )

    matching = [
        item
        for item in repository.all()
        if item.summary == "Prepare deployment report"
        and item.event_type == OrganizationEventType.TASK_CREATED
    ]

    assert len(matching) == 1
