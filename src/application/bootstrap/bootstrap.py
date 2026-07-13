"""
Application bootstrap.
"""

from __future__ import annotations

from application.cognitive import (
    SimpleCognitiveEngine,
)

from .container import (
    ApplicationContainer,
)
from application.pipeline.pipeline import (
    PolisPipeline,
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
    SimpleReasoningService,
)

def bootstrap(
) -> ApplicationContainer:
    """
    Assemble the complete POLIS
    application.
    """
    repository = InMemoryKnowledgeRepository()
    validator = SimpleKnowledgeValidator(
        repository,
    )
    observation_registry = ObservationRuleRegistry()

    observation_registry.register(
        KnowledgeObservationRule(),
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
        reasoning_service=None,
    )
    reasoning = SimpleReasoningService(
        repository,
    )
    engine = SimpleCognitiveEngine(pipeline,reasoning,)
    return ApplicationContainer(engine=engine,repository=repository,)