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
from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
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

    communication_repository = (
        InMemoryCommunicationRepository()
    )

    class FakeLLM:
        def generate(self, prompt: str) -> str:
            return "We use PostgreSQL."

    reasoning = SimpleReasoningService(
        repository=repository,
        communication_repository=(
            communication_repository
        ),
        llm_client=FakeLLM(),
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
            body="We use PostgreSQL as our database.",
        ),
    )
    communication_repository.save(
        communication
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


def test_cognitive_engine_preserves_requester_context_for_calendar_agent():
    from domain.reasoning import Answer
    from domain.reasoning.value_objects.conversation_context import (
        ConversationContext,
    )

    class FakeQuestionAnswering:
        def retrieve_evidence(self, question):
            return []

        def answer_from_evidence(self, question, evidence):
            return Answer(text="Calendar evidence checked.")

        def answer(self, question):
            return Answer(text="Fallback answer.")

    class FakeCalendarAgent:
        def __init__(self):
            self.received_question = None

        def retrieve_evidence(self, question):
            self.received_question = question
            return []

    calendar_agent = FakeCalendarAgent()
    engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=FakeQuestionAnswering(),
        calendar_agent=calendar_agent,
    )

    question = Question(
        text="What is on my calendar?",
        context=ConversationContext(
            user_id="U_TARGET",
            channel_id="C_MAIN",
            thread_ts="123.456",
        ),
    )

    engine.ask(question)

    assert calendar_agent.received_question is question
    assert calendar_agent.received_question.context.user_id == "U_TARGET"