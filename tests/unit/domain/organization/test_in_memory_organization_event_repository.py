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


def test_different_sources_with_same_text_remain_distinct():
    repository = InMemoryOrganizationEventRepository()

    event1 = make_event(OrganizationEventType.TASK_CREATED, "slack-1")
    event2 = make_event(OrganizationEventType.TASK_CREATED, "slack-2")

    repository.save(event1, source_type="slack", source_event_id="slack-1")
    repository.save(event2, source_type="slack", source_event_id="slack-2")

    assert len(repository.all()) == 2
    assert repository.find_by_source_event("slack", "slack-1", OrganizationEventType.TASK_CREATED) is event1
    assert repository.find_by_source_event("slack", "slack-2", OrganizationEventType.TASK_CREATED) is event2


def test_find_by_source_and_correlation():
    from domain.common.identifier import Identifier

    repository = InMemoryOrganizationEventRepository()

    corr1 = Identifier(business_id="meeting-100")
    corr2 = Identifier(business_id="meeting-200")

    task = make_event(OrganizationEventType.TASK_CREATED, "seg-1")
    decision = make_event(OrganizationEventType.DECISION_MADE, "seg-1")
    other_task = make_event(OrganizationEventType.TASK_CREATED, "seg-2")

    repository.save(task, source_type="teams", source_event_id="seg-1", correlation_id=corr1)
    repository.save(decision, source_type="teams", source_event_id="seg-1", correlation_id=corr1)
    repository.save(other_task, source_type="teams", source_event_id="seg-2", correlation_id=corr2)

    source_events = repository.find_by_source("teams", "seg-1")
    assert len(source_events) == 2
    assert {e.event_type for e in source_events} == {
        OrganizationEventType.TASK_CREATED,
        OrganizationEventType.DECISION_MADE,
    }

    corr1_events = repository.find_by_correlation(corr1)
    assert len(corr1_events) == 2

    corr2_events = repository.find_by_correlation(corr2)
    assert len(corr2_events) == 1
    assert corr2_events[0] is other_task


def test_repository_validates_required_source_identity():
    import pytest

    repository = InMemoryOrganizationEventRepository()
    event = make_event(OrganizationEventType.TASK_CREATED)

    with pytest.raises(ValueError, match="source_type cannot be empty"):
        repository.save(event, source_type="", source_event_id="123")

    with pytest.raises(ValueError, match="source_event_id cannot be empty"):
        repository.save(event, source_type="slack", source_event_id="   ")
