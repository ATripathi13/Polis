from application.pipeline.pipeline import PolisPipeline

from application.services.knowledge_acceptance_service import (
    KnowledgeAcceptanceService,
)

from domain.common.identifier import Identifier

from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeRuleRegistry,
    KnowledgeDiscoveryRule,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)

from domain.observation import (
    Observation,
    ObservationRule,
    ObservationRuleRegistry,
    ObservationType,
    RuleBasedObservationExtractor,
)

from domain.organization import (
    InMemoryOrganizationEventRepository,
    OrganizationEvent,
    OrganizationEventRule,
    OrganizationEventRuleRegistry,
    OrganizationEventType,
    RuleBasedOrganizationEventBuilder,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from engines.communication.domain.enums import (
    EventSource,
)

from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)

from engines.knowledge.infrastructure.indexing import (
    NullKnowledgeIndexer,
)


class FakeApprovalObservationRule(ObservationRule):
    @property
    def priority(self):
        return 60

    def extract(self, communication):
        return [
            Observation(
                observation_type=ObservationType.APPROVAL,
                summary="Deployment approved.",
                confidence=0.95,
                evidence=[communication.source_event_id],
            )
        ]


class FakeApprovalOrganizationRule(OrganizationEventRule):
    @property
    def priority(self):
        return 30

    def build(self, observations):
        return [
            OrganizationEvent(
                event_type=OrganizationEventType.APPROVAL_GRANTED,
                summary=observation.summary,
                observations=[observation],
                confidence=observation.confidence,
            )
            for observation in observations
            if observation.observation_type == ObservationType.APPROVAL
        ]


def test_pipeline_persists_approval_event():
    communication = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="approval-1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="john",
            ),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="general",
            ),
            name="general",
            channel_type="slack",
        ),
        content=Content(
            body="The deployment is approved.",
        ),
    )

    observation_registry = ObservationRuleRegistry()
    observation_registry.register(FakeApprovalObservationRule())

    organization_registry = OrganizationEventRuleRegistry()
    organization_registry.register(FakeApprovalOrganizationRule())

    repository = InMemoryKnowledgeRepository()
    knowledge_builder = RuleBasedKnowledgeBuilder(
        KnowledgeRuleRegistry()
    )
    knowledge_builder._registry.register(KnowledgeDiscoveryRule())

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=RuleBasedObservationExtractor(
            observation_registry,
        ),
        organization_builder=RuleBasedOrganizationEventBuilder(
            organization_registry,
        ),
        knowledge_builder=knowledge_builder,
        knowledge_validator=SimpleKnowledgeValidator(
            repository,
            NullKnowledgeIndexer(),
        ),
        knowledge_acceptance_service=KnowledgeAcceptanceService(
            repository,
        ),
        reasoning_service=None,
        organization_event_repository=(
            InMemoryOrganizationEventRepository()
        ),
    )

    pipeline.process(communication)

    persisted_event = (
        pipeline._organization_event_repository.find_by_source_event(
            "slack",
            "approval-1",
            OrganizationEventType.APPROVAL_GRANTED,
        )
    )

    assert persisted_event is not None
    assert persisted_event.summary == "Deployment approved."
