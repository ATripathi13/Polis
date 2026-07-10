from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)

from domain.knowledge import (
    KnowledgeDiscoveryRule,
)


def test_build_candidate():

    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_DISCOVERED,
        summary="Organization uses PostgreSQL.",
    )

    rule = KnowledgeDiscoveryRule()

    candidates = rule.build(event)

    assert len(candidates) == 1

    assert (
        candidates[0].summary
        == "Organization uses PostgreSQL."
    )