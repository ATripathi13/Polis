from application.cognitive import (
    SimpleCognitiveEngine,
)

from application.pipeline.pipeline import (
    PolisPipeline,
)

from domain.common.identifier import (
    Identifier,
)

from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeDiscoveryRule,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)

from domain.observation import (
    KnowledgeObservationRule,
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
)

from domain.organization import (
    KnowledgeOrganizationRule,
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
)

from domain.reasoning import (
    Question,
    SimpleReasoningService,
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

from domain.reasoning.rankers.keyword_ranker import (
    KeywordRanker,
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

def test_cognitive_engine():

    repository = InMemoryKnowledgeRepository()
    knowledge_acceptance_service = KnowledgeAcceptanceService(
        repository,
    )
    validator = SimpleKnowledgeValidator(
        repository,
        NullKnowledgeIndexer(),
    )

    observation_registry = ObservationRuleRegistry()

    observation_registry.register(
        KnowledgeObservationRule(
            FakeKnowledgeUnderstanding(),
        ),
    )

    observation_extractor = (
        RuleBasedObservationExtractor(
            observation_registry,
        )
    )

    organization_registry = (
        OrganizationEventRuleRegistry()
    )

    organization_registry.register(
        KnowledgeOrganizationRule(),
    )

    organization_builder = (
        RuleBasedOrganizationEventBuilder(
            organization_registry,
        )
    )

    knowledge_registry = KnowledgeRuleRegistry()

    knowledge_registry.register(
        KnowledgeDiscoveryRule(),
    )

    knowledge_builder = (
        RuleBasedKnowledgeBuilder(
            knowledge_registry,
        )
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

    reasoning = SimpleReasoningService(
        repository=repository,
        ranker=KeywordRanker(),
    )

    engine = SimpleCognitiveEngine(
        pipeline,
        reasoning,
    )

    communication = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="1",
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
            body="We use PostgreSQL.",
        ),
    )

    engine.learn(
        communication,
    )
    stored = repository.all()

    print(stored)

    assert len(stored) == 1

    answer = engine.ask(
        Question(
            text="What database do we use?",
        )
    )

    assert (
        answer.text
        == "We use PostgreSQL."
    )