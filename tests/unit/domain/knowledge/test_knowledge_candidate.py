from domain.knowledge import (
    KnowledgeCandidate,
    KnowledgeSubject,
)

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)


def test_create_candidate():

    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_DISCOVERED,
        summary="Database changed.",
    )

    subject = KnowledgeSubject(
        kind="technology",
        identifier="production_database",
    )
    candidate = KnowledgeCandidate(
        subject=subject,
        summary="Organization uses PostgreSQL.",
        supporting_events=[event],
    )
    assert (
        candidate.summary
        == "Organization uses PostgreSQL."
    )

    assert len(
        candidate.supporting_events
    ) == 1

    assert (
        candidate.confidence
        == 1.0
    )
    assert (
        candidate.subject.identifier
        == "production_database"
    )