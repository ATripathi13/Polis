"""
Production-grade tests for the Organizational Event Engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from domain.common.identifier import Identifier
from domain.observation import (
    Observation,
    ObservationType,
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
    OperationalObservationRule,
    KnowledgeObservationRule,
    QuestionObservationRule,
)
from domain.organization import (
    InMemoryOrganizationEventRepository,
    OrganizationEvent,
    OrganizationEventType,
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
    OperationalOrganizationRule as OrgOperationalRule,
    KnowledgeOrganizationRule as OrgKnowledgeRule,
    QuestionOrganizationRule as OrgQuestionRule,
    OrganizationalIntentOrganizationRule as OrgIntentRule,
)
from domain.operations import (
    OperationalItemStatus,
    OperationalItemType,
)
from application.operations import OperationalItemService
from application.pipeline.pipeline import PolisPipeline
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeRuleRegistry,
    KnowledgeDiscoveryRule,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)
from engines.knowledge.infrastructure.indexing import NullKnowledgeIndexer
from application.services.knowledge_acceptance_service import (
    KnowledgeAcceptanceService,
)


class InMemoryOperationalRepository:
    def __init__(self):
        self.items = []

    def save(self, item):
        for idx, existing in enumerate(self.items):
            if existing.identifier == item.identifier:
                self.items[idx] = item
                return item
        self.items.append(item)
        return item

    def find_by_source_event(self, source_type, source_event_id, item_type):
        for item in self.items:
            if (
                item.source_type == source_type
                and item.source_event_id == source_event_id
                and item.item_type == item_type
            ):
                return item
        return None


def test_event_model_invariants_and_temporal_correlation():
    now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
    corr_id = Identifier(business_id="slack-thread-100")

    obs = Observation(
        observation_type=ObservationType.TASK,
        summary="John to deploy service",
        confidence=0.9,
        evidence=["msg-456"],
        correlation_id=corr_id,
        occurred_at=now,
    )

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="John to deploy service",
        observations=[obs],
        confidence=0.9,
        correlation_id=corr_id,
        occurred_at=now,
    )

    assert event.event_type == OrganizationEventType.TASK_CREATED
    assert event.summary == "John to deploy service"
    assert event.confidence == 0.9
    assert len(event.observations) == 1
    assert event.correlation_id == corr_id
    assert event.occurred_at == now

    # Rejection of empty summary
    with pytest.raises(ValueError, match="summary must not be empty"):
        OrganizationEvent(
            event_type=OrganizationEventType.TASK_CREATED,
            summary="   ",
        )

    # Rejection of invalid confidence
    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        OrganizationEvent(
            event_type=OrganizationEventType.TASK_CREATED,
            summary="Valid summary",
            confidence=1.1,
        )


def test_all_meaningful_observations_mapped_deterministically():
    registry = OrganizationEventRuleRegistry()
    registry.register(OrgQuestionRule())
    registry.register(OrgIntentRule())
    registry.register(OrgOperationalRule())
    registry.register(OrgKnowledgeRule())

    builder = RuleBasedOrganizationEventBuilder(registry)

    observations = [
        Observation(
            observation_type=ObservationType.QUESTION,
            summary="Where is the cluster hosted?",
        ),
        Observation(
            observation_type=ObservationType.APPROVAL,
            summary="Cluster migration approved",
        ),
        Observation(
            observation_type=ObservationType.CONTRADICTION,
            summary="Budget conflict noted",
        ),
        Observation(
            observation_type=ObservationType.ALERT,
            summary="Access policy violated",
        ),
        Observation(
            observation_type=ObservationType.SUMMARY_REQUEST,
            summary="Please summarize the incident",
        ),
        Observation(
            observation_type=ObservationType.DECISION,
            summary="Decided on AWS eu-central-1",
        ),
        Observation(
            observation_type=ObservationType.RISK,
            summary="Latency risk in us-east",
        ),
        Observation(
            observation_type=ObservationType.TASK,
            summary="Set up VPC peering",
        ),
        Observation(
            observation_type=ObservationType.KNOWLEDGE,
            summary="Kubernetes version is 1.29",
        ),
        Observation(
            observation_type=ObservationType.UNKNOWN,
            summary="Arbitrary chatter",
        ),
    ]

    events = builder.build(observations)

    event_types = [e.event_type for e in events]
    assert OrganizationEventType.QUESTION_ASKED in event_types
    assert OrganizationEventType.APPROVAL_GRANTED in event_types
    assert OrganizationEventType.CONTRADICTION_DETECTED in event_types
    assert OrganizationEventType.POLICY_VIOLATION in event_types
    assert OrganizationEventType.SUMMARY_REQUESTED in event_types
    assert OrganizationEventType.DECISION_MADE in event_types
    assert OrganizationEventType.RISK_IDENTIFIED in event_types
    assert OrganizationEventType.TASK_CREATED in event_types
    assert OrganizationEventType.KNOWLEDGE_DISCOVERED in event_types
    assert OrganizationEventType.UNKNOWN not in event_types
    assert len(events) == 9  # UNKNOWN correctly produced nothing


def test_task_lifecycle_update_and_completion_rules():
    op_rule = OrgOperationalRule()

    task_created_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Create backups before migration",
    )
    task_updated_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Task updated: backup in progress",
    )
    task_completed_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Backup task completed",
    )

    events = op_rule.build([
        task_created_obs,
        task_updated_obs,
        task_completed_obs,
    ])

    assert [e.event_type for e in events] == [
        OrganizationEventType.TASK_CREATED,
        OrganizationEventType.TASK_UPDATED,
        OrganizationEventType.TASK_COMPLETED,
    ]


def test_in_memory_builder_deduplication_of_duplicate_rules():
    from domain.organization.rules import OrganizationEventRule

    class RuleA(OrganizationEventRule):
        @property
        def priority(self):
            return 10
        def build(self, observations):
            return [
                OrganizationEvent(
                    event_type=OrganizationEventType.DECISION_MADE,
                    summary="Approved RFC 42",
                    observations=observations,
                )
            ]

    class RuleB(OrganizationEventRule):
        @property
        def priority(self):
            return 20
        def build(self, observations):
            return [
                OrganizationEvent(
                    event_type=OrganizationEventType.DECISION_MADE,
                    summary="Approved RFC 42",
                    observations=observations,
                )
            ]

    obs = Observation(
        observation_type=ObservationType.DECISION,
        summary="Approved RFC 42",
        evidence=["rfk-42-source"],
    )

    registry = OrganizationEventRuleRegistry()
    registry.register(RuleA())
    registry.register(RuleB())

    builder = RuleBasedOrganizationEventBuilder(registry)
    events = builder.build([obs])

    # Should deduplicate in memory preserving highest priority rule's event
    assert len(events) == 1
    assert events[0].summary == "Approved RFC 42"
    assert events[0].event_type == OrganizationEventType.DECISION_MADE


def test_end_to_end_pipeline_provenance_correlation_and_lifecycle():
    corr_id = Identifier(business_id="thread-migration-999")
    now = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)

    comm = CommunicationEvent.create(
        correlation_id=corr_id,
        source=EventSource.MICROSOFT_TEAMS,
        source_event_id="teams-msg-999",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="alice",
                external_ids={"microsoft_teams": "alice-teams"},
            ),
            display_name="Alice",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="devops-channel",
            ),
            name="devops",
            channel_type="teams",
        ),
        content=Content(
            body="Task completed: migration of payments database",
        ),
    )

    # Observation rule
    class FakeOpUnderstanding:
        def analyze(self, text):
            return {
                "is_operational": True,
                "type": "task",
                "summary": "Migration of payments database completed",
                "confidence": 0.98,
                "status": "completed",
            }

    obs_registry = ObservationRuleRegistry()
    obs_registry.register(
        OperationalObservationRule(FakeOpUnderstanding())
    )
    obs_extractor = RuleBasedObservationExtractor(obs_registry)

    org_registry = OrganizationEventRuleRegistry()
    org_registry.register(OrgOperationalRule())
    org_builder = RuleBasedOrganizationEventBuilder(org_registry)

    knowledge_registry = KnowledgeRuleRegistry()
    knowledge_registry.register(KnowledgeDiscoveryRule())
    knowledge_builder = RuleBasedKnowledgeBuilder(knowledge_registry)

    knowledge_repo = InMemoryKnowledgeRepository()
    knowledge_acceptance = KnowledgeAcceptanceService(knowledge_repo)
    validator = SimpleKnowledgeValidator(knowledge_repo, NullKnowledgeIndexer())

    op_repo = InMemoryOperationalRepository()
    op_service = OperationalItemService(op_repo)

    event_repo = InMemoryOrganizationEventRepository()

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=obs_extractor,
        organization_builder=org_builder,
        knowledge_builder=knowledge_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=knowledge_acceptance,
        reasoning_service=None,
        operational_item_service=op_service,
        organization_event_repository=event_repo,
    )

    pipeline.process(comm)

    # Check that event was persisted with canonical source identity and correlation
    persisted = event_repo.find_by_source_event(
        "microsoft_teams",
        "teams-msg-999",
        OrganizationEventType.TASK_COMPLETED,
    )
    assert persisted is not None
    assert persisted.event_type == OrganizationEventType.TASK_COMPLETED
    assert persisted.correlation_id == corr_id
    assert persisted.occurred_at is not None

    # Check correlation query
    correlated_events = event_repo.find_by_correlation(corr_id)
    assert len(correlated_events) == 1
    assert correlated_events[0] is persisted

    # Check operational item created downstream with COMPLETED status
    assert len(op_repo.items) == 1
    op_item = op_repo.items[0]
    assert op_item.item_type == OperationalItemType.TASK
    assert op_item.status == OperationalItemStatus.COMPLETED
    assert op_item.source_type == "microsoft_teams"
    assert op_item.source_event_id == "teams-msg-999"
