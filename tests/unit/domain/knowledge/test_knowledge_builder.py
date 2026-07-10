from domain.knowledge import (
    KnowledgeBuilder,
)


class DummyBuilder(
    KnowledgeBuilder,
):

    def build(
        self,
        event,
    ):
        return []


def test_builder():

    builder = DummyBuilder()

    assert isinstance(
        builder,
        KnowledgeBuilder,
    )