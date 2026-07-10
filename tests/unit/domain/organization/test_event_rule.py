from domain.organization import (
    OrganizationEventRule,
)


class DummyRule(
    OrganizationEventRule,
):

    def build(
        self,
        bundle,
    ):
        return []


def test_event_rule():

    rule = DummyRule()

    assert isinstance(
        rule,
        OrganizationEventRule,
    )