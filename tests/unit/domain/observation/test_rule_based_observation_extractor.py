from domain.observation import (
    Observation,
    ObservationType,
    RuleBasedObservationExtractor,
    ObservationRuleRegistry,
)

from domain.observation.rules import (
    QuestionObservationRule,
)

from engines.communication.domain.value_objects import (
    Content,
)

from unit.communication.test_communication_event import (
    create_test_event,
)


def test_extract_observations():

    registry = ObservationRuleRegistry()

    registry.register(
        QuestionObservationRule(),
    )

    extractor = RuleBasedObservationExtractor(
        registry,
    )

    event = create_test_event()

    event.content = Content(
        body="What database do we use?",
    )

    observations = extractor.extract(
        event,
    )

    assert len(observations) == 1

    assert (
        observations[0].observation_type
        == ObservationType.QUESTION
    )


class FailingRule:
    @property
    def priority(self):
        return 10

    def extract(self, communication):
        raise RuntimeError("rule failure")


class WorkingRule:
    @property
    def priority(self):
        return 20

    def extract(self, communication):
        return [
            Observation(
                observation_type=ObservationType.QUESTION,
                summary="Fallback question",
                confidence=1.0,
            )
        ]


def test_extractor_continues_when_observation_rule_fails():

    registry = ObservationRuleRegistry()

    registry.register(FailingRule())
    registry.register(WorkingRule())

    extractor = RuleBasedObservationExtractor(
        registry,
    )

    event = create_test_event()

    observations = extractor.extract(
        event,
    )

    assert len(observations) == 1
    assert observations[0].summary == "Fallback question"
