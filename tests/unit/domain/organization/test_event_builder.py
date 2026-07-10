from domain.organization import (
    OrganizationEventBuilder,
)


class DummyBuilder(
    OrganizationEventBuilder,
):

    def build(
        self,
        bundle,
    ):
        return []


def test_builder():

    builder = DummyBuilder()

    assert isinstance(
        builder,
        OrganizationEventBuilder,
    )