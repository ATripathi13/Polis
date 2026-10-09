from domain.observation import Observation, ObservationType
from domain.organization import (
    KnowledgeOrganizationRule,
    OperationalOrganizationRule,
    OrganizationEventType,
    QuestionOrganizationRule,
)


def test_supported_observations_map_to_canonical_events():

    observations = [
        Observation(
            observation_type=ObservationType.QUESTION,
            summary="What database do we use?",
        ),
        Observation(
            observation_type=ObservationType.KNOWLEDGE,
            summary="We use PostgreSQL.",
        ),
        Observation(
            observation_type=ObservationType.TASK,
            summary="Prepare the deployment report.",
        ),
        Observation(
            observation_type=ObservationType.DECISION,
            summary="The deployment will happen Friday.",
        ),
        Observation(
            observation_type=ObservationType.RISK,
            summary="The migration may exceed the deadline.",
        ),
    ]

    question_events = QuestionOrganizationRule().build(
        observations
    )

    operational_events = OperationalOrganizationRule().build(
        observations
    )

    knowledge_events = KnowledgeOrganizationRule().build(
        observations
    )

    events = (
        question_events
        + operational_events
        + knowledge_events
    )

    assert [event.event_type for event in events] == [
        OrganizationEventType.QUESTION_ASKED,
        OrganizationEventType.TASK_CREATED,
        OrganizationEventType.DECISION_MADE,
        OrganizationEventType.RISK_IDENTIFIED,
        OrganizationEventType.KNOWLEDGE_DISCOVERED,
    ]
