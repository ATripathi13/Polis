from datetime import datetime, timezone

from domain.observation import (
    ObservationType,
)

from domain.observation.rules import (
    QuestionObservationRule,
)

from engines.communication.domain.value_objects import (
    Content,
)

from tests.unit.communication.test_communication_event import (
    create_test_event,
)


def test_extract_question_observation():

    event = create_test_event()

    event.content = Content(
        body="What database do we use?",
        metadata={"source_timestamp": "1712345678.123456"},
    )

    rule = QuestionObservationRule()

    observations = rule.extract(event)

    assert len(observations) == 1

    assert (
        observations[0].observation_type
        == ObservationType.QUESTION
    )

    assert observations[0].evidence == [
        "1712345678.123456"
    ]
    assert observations[0].occurred_at == datetime.fromtimestamp(
        1712345678.123456,
        tz=timezone.utc,
    )


def test_ignore_non_question():

    event = create_test_event()

    event.content = Content(
        body="We use PostgreSQL.",
    )

    rule = QuestionObservationRule()

    observations = rule.extract(event)

    assert observations == []
