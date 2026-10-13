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


def test_rule_priority_ordering_is_strictly_deterministic():
    class RulePriority30(OrganizationEventRule):
        @property
        def priority(self):
            return 30
        def build(self, observations):
            return []

    class RulePriority10(OrganizationEventRule):
        @property
        def priority(self):
            return 10
        def build(self, observations):
            return []

    class RulePriority20A(OrganizationEventRule):
        @property
        def priority(self):
            return 20
        def build(self, observations):
            return []

    class RulePriority20B(OrganizationEventRule):
        @property
        def priority(self):
            return 20
        def build(self, observations):
            return []

    registry = OrganizationEventRuleRegistry()
    r30 = RulePriority30()
    r10 = RulePriority10()
    r20b = RulePriority20B()
    r20a = RulePriority20A()

    # Register in arbitrary order
    registry.register(r30)
    registry.register(r20b)
    registry.register(r10)
    registry.register(r20a)

    rules = registry.rules
    assert [type(r).__name__ for r in rules] == [
        "RulePriority10",
        "RulePriority20A",
        "RulePriority20B",
        "RulePriority30",
    ]


def test_duplicate_rule_instance_not_registered_twice():
    registry = OrganizationEventRuleRegistry()
    rule = DummyRule()

    registry.register(rule)
    registry.register(rule)

    assert len(registry.rules) == 1