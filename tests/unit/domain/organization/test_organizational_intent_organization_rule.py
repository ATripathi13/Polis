from domain.observation import Observation, ObservationType
from domain.organization import OrganizationEventType
from domain.organization.rules import (
    OrganizationalIntentOrganizationRule,
)


def test_organizational_intent_events_map_correctly():
    observations = [
        Observation(
            observation_type=ObservationType.APPROVAL,
            summary="Deployment approved.",
            confidence=0.95,
        ),
        Observation(
            observation_type=ObservationType.CONTRADICTION,
            summary="The deadline conflicts with the previous commitment.",
            confidence=0.90,
        ),
        Observation(
            observation_type=ObservationType.ALERT,
            summary="The required approval policy was bypassed.",
            confidence=0.92,
        ),
        Observation(
            observation_type=ObservationType.SUMMARY_REQUEST,
            summary="Provide a summary of the meeting.",
            confidence=0.99,
        ),
    ]

    events = OrganizationalIntentOrganizationRule().build(
        observations
    )

    assert [event.event_type for event in events] == [
        OrganizationEventType.APPROVAL_GRANTED,
        OrganizationEventType.CONTRADICTION_DETECTED,
        OrganizationEventType.POLICY_VIOLATION,
        OrganizationEventType.SUMMARY_REQUESTED,
    ]

    assert all(
        len(event.observations) == 1
        for event in events
    )


def test_unrelated_observations_are_ignored():
    observation = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="We use PostgreSQL.",
    )

    events = OrganizationalIntentOrganizationRule().build(
        [observation]
    )

    assert events == []
