from domain.observation import (
    Observation,
    ObservationType,
)

from domain.organization import (
    KnowledgeOrganizationRule,
    OrganizationEventType,
)


def test_build_knowledge_event():

    observation = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="We use PostgreSQL.",
    )

    rule = KnowledgeOrganizationRule()

    events = rule.build(
        [
            observation,
        ]
    )

    assert len(events) == 1

    assert (
        events[0].event_type
        == OrganizationEventType.KNOWLEDGE_DISCOVERED
    )

    assert (
        events[0].summary
        == "We use PostgreSQL."
    )