from domain.observation import (
    ObservationBundle,
)

from domain.organization import (
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
)

from domain.organization.rules import (
    OrganizationEventRule,
)


class DummyRule(
    OrganizationEventRule,
):

    def build(
        self,
        bundle: ObservationBundle,
    ):
        return []


def test_rule_based_builder():

    registry = OrganizationEventRuleRegistry()

    registry.register(
        DummyRule(),
    )

    builder = RuleBasedOrganizationEventBuilder(
        registry,
    )

    bundle = ObservationBundle()

    assert builder.build(bundle) == []