from domain.observation import (
    ObservationBundle,
)

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
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
class FailingOrganizationRule:
    @property
    def priority(self):
        return 10

    def build(self, observations):
        raise RuntimeError("organization rule failure")


class WorkingOrganizationRule:
    @property
    def priority(self):
        return 20

    def build(self, observations):
        return [
            OrganizationEvent(
                event_type=OrganizationEventType.QUESTION_ASKED,
                summary="Recovered organization event",
            )
        ]


def test_builder_continues_when_organization_rule_fails():

    registry = OrganizationEventRuleRegistry()

    registry.register(FailingOrganizationRule())
    registry.register(WorkingOrganizationRule())

    builder = RuleBasedOrganizationEventBuilder(
        registry,
    )

    events = builder.build([])

    assert len(events) == 1
    assert (
        events[0].event_type
        == OrganizationEventType.QUESTION_ASKED
    )
    assert events[0].summary == "Recovered organization event"
