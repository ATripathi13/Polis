from domain.organization import (
    InMemoryOrganizationEventRepository,
    OrganizationEvent,
    OrganizationEventType,
)

from domain.observation import (
    Observation,
    ObservationType,
)


def make_event(
    event_type: OrganizationEventType,
    source_event_id: str = "slack-123",
) -> OrganizationEvent:
    observation = Observation(
        observation_type=ObservationType.TASK,
        summary="Prepare deployment report",
        confidence=0.9,
        evidence=[source_event_id],
    )

    return OrganizationEvent(
        event_type=event_type,
        summary="Prepare deployment report",
        observations=[observation],
        confidence=0.9,
    )


def test_save_and_find_by_source_event():
    repository = InMemoryOrganizationEventRepository()

    event = make_event(OrganizationEventType.TASK_CREATED)

    repository.save(
        event,
        source_type="slack",
        source_event_id="slack-123",
    )

    loaded = repository.find_by_source_event(
        "slack",
        "slack-123",
        OrganizationEventType.TASK_CREATED,
    )

    assert loaded is event


def test_duplicate_source_event_and_type_is_not_stored_twice():
    repository = InMemoryOrganizationEventRepository()

    first = make_event(
        OrganizationEventType.TASK_CREATED,
    )
    second = make_event(
        OrganizationEventType.TASK_CREATED,
    )

    repository.save(
        first,
        source_type="slack",
        source_event_id="slack-123",
    )
    repository.save(
        second,
        source_type="slack",
        source_event_id="slack-123",
    )

    assert repository.find_by_source_event(
        "slack",
        "slack-123",
        OrganizationEventType.TASK_CREATED,
    ) is first

    assert len(repository.all()) == 1


def test_same_source_event_can_produce_different_event_types():
    repository = InMemoryOrganizationEventRepository()

    task = make_event(
        OrganizationEventType.TASK_CREATED,
    )
    decision = make_event(
        OrganizationEventType.DECISION_MADE,
    )

    repository.save(
        task,
        source_type="slack",
        source_event_id="slack-123",
    )
    repository.save(
        decision,
        source_type="slack",
        source_event_id="slack-123",
    )

    assert len(repository.all()) == 2
