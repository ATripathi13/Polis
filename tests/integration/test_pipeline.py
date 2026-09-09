from application.pipeline.pipeline import PolisPipeline

from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
    KnowledgeDiscoveryRule,
    SimpleKnowledgeValidator,
)

from domain.organization import (
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
)

from domain.observation import (
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.common.identifier import Identifier

from engines.communication.domain.enums import (
    EventSource,
)

from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    Content,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    Content,
    CommunicationIdentity,
)
from domain.observation import (
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
    KnowledgeObservationRule,
)

from domain.organization import (
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
    KnowledgeOrganizationRule,
)

from domain.knowledge import (
    ValidationStatus,
)

from engines.knowledge.infrastructure.indexing import (
    NullKnowledgeIndexer,
)

from application.services.knowledge_acceptance_service import (
    KnowledgeAcceptanceService,
)
class FakeKnowledgeUnderstanding:
    def analyze(self, text):
        return {
            "is_knowledge": True,
            "summary": "We use PostgreSQL.",
            "confidence": 0.95,
        }
def test_polis_pipeline():
    communication = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="john",
                external_ids={
                    "slack": "U123456",
                },
            ),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="general",
                external_ids={
                    "slack": "C123456",
                },
            ),
            name="general",
            channel_type="slack",
        ),
        content=Content(
            body="We use PostgreSQL.",
        ),
    )

    observation_registry = ObservationRuleRegistry()

    observation_registry.register(
        KnowledgeObservationRule(
            FakeKnowledgeUnderstanding(),
        ),
    )
    # Register your observation rules
    # Example:
    # observation_registry.register(
    #     QuestionObservationRule()
    # )

    observation_extractor = RuleBasedObservationExtractor(
        observation_registry,
    )

    organization_registry = OrganizationEventRuleRegistry()
    
    organization_registry.register(
        KnowledgeOrganizationRule(),
    )
    # Register organization rules here

    organization_builder = RuleBasedOrganizationEventBuilder(
        organization_registry,
    )

    knowledge_registry = KnowledgeRuleRegistry()

    knowledge_registry.register(
        KnowledgeDiscoveryRule(),
    )

    knowledge_builder = RuleBasedKnowledgeBuilder(
        knowledge_registry,
    )

    repository = InMemoryKnowledgeRepository()
    knowledge_acceptance_service = KnowledgeAcceptanceService(
        repository,
    )
    validator = SimpleKnowledgeValidator(
        repository,
        NullKnowledgeIndexer(),
    )

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=observation_extractor,
        organization_builder=organization_builder,
        knowledge_builder=knowledge_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=knowledge_acceptance_service,
        reasoning_service=None,
    )


    results = pipeline.process(
        communication,
    )

    assert len(results) == 1

    assert (
        results[0].status
        == ValidationStatus.ACCEPTED
    )

    stored = repository.all()

    assert len(stored) == 1

    assert (
        stored[0].summary
        == "We use PostgreSQL."
    )