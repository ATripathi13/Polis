from domain.common.entity import Entity


class DummyEntity(Entity):
    pass


def test_entity_identity() -> None:
    entity = DummyEntity()

    assert entity.graph_id is not None


def test_entity_metadata() -> None:
    entity = DummyEntity()

    entity.metadata["source"] = "test"

    assert entity.metadata["source"] == "test"


def test_entity_soft_delete() -> None:
    entity = DummyEntity()

    entity.mark_deleted()

    assert entity.deleted_at is not None


def test_entity_domain_events() -> None:
    entity = DummyEntity()

    entity.add_domain_event("event")

    events = entity.pull_domain_events()

    assert len(events) == 1

    assert events[0] == "event"

    assert len(entity.pull_domain_events()) == 0