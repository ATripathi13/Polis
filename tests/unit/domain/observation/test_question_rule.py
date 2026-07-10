from domain.observation import (
    ObservationType,
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


def test_extract_question_observation():

    event = create_test_event()

    event.content = Content(
        body="What database do we use?",
    )

    rule = QuestionObservationRule()

    observations = rule.extract(event)

    assert len(observations) == 1

    assert (
        observations[0].observation_type
        == ObservationType.QUESTION
    )


def test_ignore_non_question():

    event = create_test_event()

    event.content = Content(
        body="We use PostgreSQL.",
    )

    rule = QuestionObservationRule()

    observations = rule.extract(event)

    assert observations == []