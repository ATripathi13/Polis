from domain.organization import (
    OrganizationEventRuleRegistry,
)

from domain.organization import (
    OrganizationEventRule,
)

from domain.observation import (
    ObservationBundle,
)


class DummyRule(
    OrganizationEventRule,
):

    @property
    def priority(self):
        return 10

    def build(
        self,
        bundle: ObservationBundle,
    ):
        return []


def test_register_rule():

    registry = OrganizationEventRuleRegistry()

    registry.register(
        DummyRule(),
    )

    assert len(registry.rules) == 1