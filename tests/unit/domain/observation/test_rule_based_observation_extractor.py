from domain.observation import (
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