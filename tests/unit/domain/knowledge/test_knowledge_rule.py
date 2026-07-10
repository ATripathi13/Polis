from domain.knowledge import (
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


def test_knowledge_rule():

    rule = DummyRule()

    assert isinstance(
        rule,
        KnowledgeCandidateRule,
    )