from application.pipeline.pipeline import PolisPipeline
from application.operations import OperationalItemService

from domain.common.identifier import Identifier
from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
)
from domain.organization import (
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
    OperationalOrganizationRule,
)
from domain.observation import (
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
    OperationalObservationRule,
)
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    Content,
    CommunicationIdentity,
)
from engines.knowledge.infrastructure.indexing import NullKnowledgeIndexer
from domain.knowledge import SimpleKnowledgeValidator
from application.services.knowledge_acceptance_service import (
    KnowledgeAcceptanceService,
)


class FakeOperationalUnderstanding:
    def analyze(self, text):
        return {
            "is_operational": True,
            "type": "task",
            "summary": "Prepare deployment report",
            "confidence": 0.95,
        }


class FakeOperationalItemRepository:
    def __init__(self):
        self.items = []

    def save(self, item):
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


def test_operations_pipeline_creates_operational_item():
    communication = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="slack-operation-1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="john",
                external_ids={"slack": "U123456"},
            ),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="general",
                external_ids={"slack": "C123456"},
            ),
            name="general",
            channel_type="slack",
        ),
        content=Content(
            body="Please prepare the deployment report by Friday.",
        ),
    )

    observation_registry = ObservationRuleRegistry()
    observation_registry.register(
        OperationalObservationRule(
            FakeOperationalUnderstanding(),
        ),
    )

    observation_extractor = RuleBasedObservationExtractor(
        observation_registry,
    )

    organization_registry = OrganizationEventRuleRegistry()
    organization_registry.register(
        OperationalOrganizationRule(),
    )

    organization_builder = RuleBasedOrganizationEventBuilder(
        organization_registry,
    )

    knowledge_registry = KnowledgeRuleRegistry()
    knowledge_builder = RuleBasedKnowledgeBuilder(
        knowledge_registry,
    )

    knowledge_repository = InMemoryKnowledgeRepository()
    knowledge_acceptance_service = KnowledgeAcceptanceService(
        knowledge_repository,
    )
    validator = SimpleKnowledgeValidator(
        knowledge_repository,
        NullKnowledgeIndexer(),
    )

    operational_repository = FakeOperationalItemRepository()
    operational_item_service = OperationalItemService(
        operational_repository,
    )

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=observation_extractor,
        organization_builder=organization_builder,
        knowledge_builder=knowledge_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=knowledge_acceptance_service,
        reasoning_service=None,
        operational_item_service=operational_item_service,
    )

    results = pipeline.process(communication)

    assert results == []
    assert len(operational_repository.items) == 1

    item = operational_repository.items[0]

    assert item.item_type.value == "task"
    assert item.summary == "Prepare deployment report"
    assert item.source_type == "slack"
    assert item.source_event_id == "slack-operation-1"
