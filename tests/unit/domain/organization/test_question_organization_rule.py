from domain.observation import (
    Observation,
    ObservationType,
)

from domain.organization import (
    OrganizationEventType,
    QuestionOrganizationRule,
)


def test_build_question_event():

    observation = Observation(
        observation_type=ObservationType.QUESTION,
        summary="What database do we use?",
        confidence=0.9,
        evidence=["slack-event-1"],
    )

    rule = QuestionOrganizationRule()

    events = rule.build(
        [
            observation,
        ]
    )

    assert len(events) == 1

    assert (
        events[0].event_type
        == OrganizationEventType.QUESTION_ASKED
    )

    assert (
        events[0].summary
        == "What database do we use?"
    )

    assert (
        events[0].confidence
        == 0.9
    )

    assert (
        events[0].observations[0].evidence
        == ["slack-event-1"]
    )
