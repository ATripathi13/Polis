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


def test_builder_deduplicates_duplicate_semantic_events():
    from domain.observation import Observation, ObservationType

    class RuleOne(OrganizationEventRule):
        @property
        def priority(self):
            return 10
        def build(self, observations):
            return [
                OrganizationEvent(
                    event_type=OrganizationEventType.TASK_CREATED,
                    summary="Deploy database",
                    observations=observations,
                )
            ]

    class RuleTwoDuplicate(OrganizationEventRule):
        @property
        def priority(self):
            return 20
        def build(self, observations):
            return [
                OrganizationEvent(
                    event_type=OrganizationEventType.TASK_CREATED,
                    summary="Deploy database",
                    observations=observations,
                )
            ]

    obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Deploy database",
        evidence=["source-123"],
    )

    registry = OrganizationEventRuleRegistry()
    registry.register(RuleOne())
    registry.register(RuleTwoDuplicate())

    builder = RuleBasedOrganizationEventBuilder(registry)
    events = builder.build([obs])

    assert len(events) == 1
    assert events[0].event_type == OrganizationEventType.TASK_CREATED
    assert events[0].summary == "Deploy database"


def test_builder_allows_different_event_types_or_summaries():
    from domain.observation import Observation, ObservationType

    class MultiRule(OrganizationEventRule):
        @property
        def priority(self):
            return 10
        def build(self, observations):
            return [
                OrganizationEvent(
                    event_type=OrganizationEventType.TASK_CREATED,
                    summary="Deploy database",
                    observations=observations,
                ),
                OrganizationEvent(
                    event_type=OrganizationEventType.DECISION_MADE,
                    summary="Deploy database",
                    observations=observations,
                ),
                OrganizationEvent(
                    event_type=OrganizationEventType.TASK_CREATED,
                    summary="Prepare release notes",
                    observations=observations,
                ),
            ]

    obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Work",
        evidence=["source-123"],
    )

    registry = OrganizationEventRuleRegistry()
    registry.register(MultiRule())

    builder = RuleBasedOrganizationEventBuilder(registry)
    events = builder.build([obs])

    assert len(events) == 3
    event_signatures = [(e.event_type, e.summary) for e in events]
    assert event_signatures == [
        (OrganizationEventType.TASK_CREATED, "Deploy database"),
        (OrganizationEventType.DECISION_MADE, "Deploy database"),
        (OrganizationEventType.TASK_CREATED, "Prepare release notes"),
    ]
