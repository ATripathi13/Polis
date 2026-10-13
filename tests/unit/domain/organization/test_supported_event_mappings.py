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


def test_task_lifecycle_mapping_semantics():
    rule = OperationalOrganizationRule()

    created_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Prepare the release notes for v2.0",
    )
    updated_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Task updated: deadline moved to Monday",
    )
    completed_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Completed the task: deploy to production",
    )
    explicit_meta_update = Observation(
        observation_type=ObservationType.TASK,
        summary="Work on authentication",
        metadata={"status": "in_progress"},
    )
    explicit_meta_complete = Observation(
        observation_type=ObservationType.TASK,
        summary="Review pull request",
        metadata={"status": "completed"},
    )

    events = rule.build([
        created_obs,
        updated_obs,
        completed_obs,
        explicit_meta_update,
        explicit_meta_complete,
    ])

    assert [e.event_type for e in events] == [
        OrganizationEventType.TASK_CREATED,
        OrganizationEventType.TASK_UPDATED,
        OrganizationEventType.TASK_COMPLETED,
        OrganizationEventType.TASK_UPDATED,
        OrganizationEventType.TASK_COMPLETED,
    ]


def test_knowledge_lifecycle_mapping_semantics():
    rule = KnowledgeOrganizationRule()

    discovered_obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="We use PostgreSQL for all relational storage.",
    )
    updated_obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="Updated: MySQL is no longer used, replaced with PostgreSQL 16.",
    )
    deprecated_obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="Deprecated: OAuth v1 is deprecated in favor of OAuth v2.",
    )
    meta_updated_obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="Authentication flow details",
        metadata={"is_update": True},
    )

    events = rule.build([
        discovered_obs,
        updated_obs,
        deprecated_obs,
        meta_updated_obs,
    ])

    assert [e.event_type for e in events] == [
        OrganizationEventType.KNOWLEDGE_DISCOVERED,
        OrganizationEventType.KNOWLEDGE_UPDATED,
        OrganizationEventType.KNOWLEDGE_UPDATED,
        OrganizationEventType.KNOWLEDGE_UPDATED,
    ]


def test_unknown_and_unmapped_observations_are_intentionally_ignored():
    from domain.organization.rules import (
        OrganizationalIntentOrganizationRule,
    )

    unknown_obs = Observation(
        observation_type=ObservationType.UNKNOWN,
        summary="Hello team, good morning!",
    )

    rules = [
        QuestionOrganizationRule(),
        OperationalOrganizationRule(),
        KnowledgeOrganizationRule(),
        OrganizationalIntentOrganizationRule(),
    ]

    for rule in rules:
        events = rule.build([unknown_obs])
        assert events == [], f"{type(rule).__name__} should not map UNKNOWN observations"
