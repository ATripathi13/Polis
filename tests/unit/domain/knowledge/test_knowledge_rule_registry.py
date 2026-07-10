from domain.knowledge import (
    KnowledgeRuleRegistry,
)

from domain.knowledge.rules import (
    KnowledgeCandidateRule,
)


class DummyRule(
    KnowledgeCandidateRule,
):

    @property
    def priority(self):
        return 10

    def build(
        self,
        event,
    ):
        return []


def test_register_rule():

    registry = KnowledgeRuleRegistry()

    registry.register(
        DummyRule(),
    )

    assert len(registry.rules) == 1