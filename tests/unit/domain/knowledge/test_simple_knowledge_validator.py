from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeCandidate,
    KnowledgeSubject,
    SimpleKnowledgeValidator,
    ValidationStatus,
)

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from engines.knowledge.infrastructure.indexing import (
    NullKnowledgeIndexer,
)

def test_accept_new_knowledge():

    repository = InMemoryKnowledgeRepository()

    validator = SimpleKnowledgeValidator(
        repository,
        NullKnowledgeIndexer(),
    )

    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_DISCOVERED,
        summary="Organization uses PostgreSQL.",
    )

    candidate = KnowledgeCandidate(
        subject=KnowledgeSubject(
            kind="technology",
            identifier="production_database",
        ),
        summary="Organization uses PostgreSQL.",
        supporting_events=[event],
    )

    result = validator.validate(candidate)

    assert result.status == ValidationStatus.ACCEPTED

    assert repository.find(
        "production_database"
    ) is not None

def test_update_existing_knowledge():

    repository = InMemoryKnowledgeRepository()

    validator = SimpleKnowledgeValidator(
        repository,
        NullKnowledgeIndexer(),
    )

    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_DISCOVERED,
        summary="PostgreSQL",
    )

    first = KnowledgeCandidate(
        subject=KnowledgeSubject(
            kind="technology",
            identifier="database",
        ),
        summary="PostgreSQL",
        supporting_events=[event],
    )

    validator.validate(first)

    second = KnowledgeCandidate(
        subject=KnowledgeSubject(
            kind="technology",
            identifier="database",
        ),
        summary="PostgreSQL 17",
        supporting_events=[event],
    )

    result = validator.validate(second)

    assert result.status == ValidationStatus.UPDATED

    assert (
        repository.find("database").summary
        == "PostgreSQL 17"
    )