from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)

from domain.knowledge import (
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
)

from domain.knowledge.rules import (
    KnowledgeCandidateRule,
)


class DummyRule(
    KnowledgeCandidateRule,
):

    def build(
        self,
        event,
    ):
        return []


def test_rule_based_builder():

    registry = KnowledgeRuleRegistry()

    registry.register(
        DummyRule(),
    )

    builder = RuleBasedKnowledgeBuilder(
        registry,
    )

    event = OrganizationEvent(
        event_type=OrganizationEventType.UNKNOWN,
        summary="Dummy",
    )

    assert builder.build(event) == []