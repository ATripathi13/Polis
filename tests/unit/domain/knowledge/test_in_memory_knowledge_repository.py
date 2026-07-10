from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeCandidate,
    KnowledgeSubject,
)

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)


def test_repository_save_and_find():

    repository = (
        InMemoryKnowledgeRepository()
    )

    event = OrganizationEvent(
        event_type=(
            OrganizationEventType
            .KNOWLEDGE_DISCOVERED
        ),
        summary="Organization uses PostgreSQL.",
    )

    candidate = KnowledgeCandidate(
        subject=KnowledgeSubject(
            kind="technology",
            identifier="production_database",
        ),
        summary="Organization uses PostgreSQL.",
        supporting_events=[
            event,
        ],
    )

    repository.save(
        candidate,
    )

    loaded = repository.find(
        "production_database",
    )

    assert loaded is not None

    assert (
        loaded.summary
        == "Organization uses PostgreSQL."
    )

    assert (
        len(repository.all())
        == 1
    )