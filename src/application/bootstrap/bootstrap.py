"""
Application bootstrap.
"""

from __future__ import annotations

from infrastructure.llm import (
    OpenRouterClient,
)

from infrastructure.llm.knowledge_understanding import (
    LLMKnowledgeUnderstanding,
)

from application.cognitive import (
    SimpleCognitiveEngine,
)

from .container import (
    ApplicationContainer,
)
from application.pipeline.pipeline import (
    PolisPipeline,
)
from application.services.knowledge_acceptance_service import (
    KnowledgeAcceptanceService,
)

from domain.knowledge import (
    KnowledgeDiscoveryRule,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)

from infrastructure.database import (
    PostgreSQLKnowledgeRepository,
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
    SimpleReasoningService,
)
from domain.reasoning.rankers import (
    KeywordRanker,
)
from engines.knowledge.infrastructure.indexing import (
    NullKnowledgeIndexer,
)
def bootstrap(
) -> ApplicationContainer:
    """
    Assemble the complete POLIS
    application.
    """
    repository = PostgreSQLKnowledgeRepository()

    indexer = NullKnowledgeIndexer()

    validator = SimpleKnowledgeValidator(
        repository=repository,
        indexer=indexer,
    )

    knowledge_acceptance_service = KnowledgeAcceptanceService(
        repository=repository,
    )

    llm_client = OpenRouterClient()

    knowledge_understanding = (
        LLMKnowledgeUnderstanding(
            llm_client,
        )
    )
    observation_registry = ObservationRuleRegistry()

    observation_registry.register(
        KnowledgeObservationRule(
            knowledge_understanding,
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
    
    reasoning = SimpleReasoningService(
        repository,
        ranker=KeywordRanker(),
    )

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=observation_extractor,
        organization_builder=organization_builder,
        knowledge_builder=knowledge_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=knowledge_acceptance_service,
        reasoning_service=reasoning,
    )

    engine = SimpleCognitiveEngine(
        pipeline,
        reasoning,
    )

    return ApplicationContainer(
        engine=engine,
        repository=repository,
    )