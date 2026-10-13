"""
Integration tests for OperationsAgent in POLIS.

Tests end-to-end pipeline dispatch, cognitive engine evidence unification,
API route integration, and coexistence with KnowledgeAgent and MeetingAgent.
"""

import pytest
from fastapi.testclient import TestClient

from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemType,
    OperationalItemStatus,
    OperationalItemPriority,
    InMemoryOperationalItemRepository,
)
from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)
from domain.organization import (
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
    OperationalOrganizationRule,
    KnowledgeOrganizationRule,
)
from domain.observation import (
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
    OperationalObservationRule,
    KnowledgeObservationRule,
)
from domain.reasoning import (
    Question,
    Answer,
    QuestionAnsweringService,
    SimpleReasoningService,
)
from domain.reasoning.rankers import KeywordRanker
from application.pipeline.pipeline import PolisPipeline
from application.operations import (
    OperationsAgent,
    OperationalItemService,
)
from application.knowledge import KnowledgeAgent
from application.cognitive import SimpleCognitiveEngine
from application.services.knowledge_acceptance_service import KnowledgeAcceptanceService
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    Content,
    CommunicationIdentity,
)
from interfaces.api.app import app
from interfaces.api.dependencies import get_operations_agent, get_cognitive_engine


class FakeOperationalUnderstanding:
    def analyze(self, text):
        return {
            "is_operational": True,
            "type": "task",
            "summary": "Deploy payment service to staging",
            "confidence": 0.95,
        }


class FakeKnowledgeUnderstanding:
    def analyze(self, text):
        return {
            "is_knowledge": True,
            "statement": "Payment service staging deploy port is 8080",
            "confidence": 0.90,
        }


class DummyQuestionAnswering(QuestionAnsweringService):
    def answer(self, question: Question) -> Answer:
        return Answer(text="Default fallback answer")

    def retrieve_evidence(self, question: Question) -> list[str]:
        return ["Org communication evidence"]

    def answer_from_evidence(self, question, evidence, fallback_evidence=None) -> Answer:
        return Answer(text=f"Answered with {len(evidence)} evidence items")


@pytest.fixture
def op_repo():
    return InMemoryOperationalItemRepository()


@pytest.fixture
def op_service(op_repo):
    return OperationalItemService(op_repo)


@pytest.fixture
def op_agent(op_repo, op_service):
    return OperationsAgent(
        repository=op_repo,
        operational_item_service=op_service,
    )


@pytest.fixture
def kn_repo():
    return InMemoryKnowledgeRepository()


@pytest.fixture
def kn_agent(kn_repo):
    return KnowledgeAgent(knowledge_repository=kn_repo)


@pytest.fixture
def full_pipeline(op_repo, op_service, op_agent, kn_repo, kn_agent):
    obs_reg = ObservationRuleRegistry()
    obs_reg.register(OperationalObservationRule(FakeOperationalUnderstanding()))
    obs_reg.register(KnowledgeObservationRule(FakeKnowledgeUnderstanding()))
    obs_extractor = RuleBasedObservationExtractor(obs_reg)

    org_reg = OrganizationEventRuleRegistry()
    org_reg.register(OperationalOrganizationRule())
    org_reg.register(KnowledgeOrganizationRule())
    org_builder = RuleBasedOrganizationEventBuilder(org_reg)

    from engines.knowledge.infrastructure.indexing import NullKnowledgeIndexer
    from domain.knowledge import KnowledgeDiscoveryRule
    kn_reg = KnowledgeRuleRegistry()
    kn_reg.register(KnowledgeDiscoveryRule())
    kn_builder = RuleBasedKnowledgeBuilder(kn_reg)
    indexer = NullKnowledgeIndexer()
    validator = SimpleKnowledgeValidator(kn_repo, indexer)
    acceptance = KnowledgeAcceptanceService(kn_repo)
    reasoning = DummyQuestionAnswering()

    return PolisPipeline(
        communication_service=None,
        observation_extractor=obs_extractor,
        organization_builder=org_builder,
        knowledge_builder=kn_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=acceptance,
        reasoning_service=reasoning,
        operational_item_service=op_service,
        knowledge_agent=kn_agent,
        operations_agent=op_agent,
    )


def _create_communication(source_event_id: str, body: str) -> CommunicationEvent:
    return CommunicationEvent.create(
        correlation_id=Identifier(business_id="corr-test-pipeline"),
        source=EventSource.SLACK,
        source_event_id=source_event_id,
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="alice",
                external_ids={"slack": "U12345"},
            ),
            display_name="Alice",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="dev",
                external_ids={"slack": "C12345"},
            ),
            name="dev",
            channel_type="slack",
        ),
        content=Content(body=body),
    )


# -----------------------------------------------------------------------------
# 1. Pipeline End-to-End Processing & OperationsAgent Dispatch
# -----------------------------------------------------------------------------

def test_pipeline_dispatches_to_operations_agent(full_pipeline, op_repo):
    comm = _create_communication("msg-101", "Please deploy payment service to staging.")

    full_pipeline.process(comm)

    open_tasks = op_repo.find_open(item_type=OperationalItemType.TASK)
    assert len(open_tasks) == 1
    assert open_tasks[0].summary == "Deploy payment service to staging"
    assert open_tasks[0].source_event_id == "msg-101"


# -----------------------------------------------------------------------------
# 2. Pipeline Idempotency Replay
# -----------------------------------------------------------------------------

def test_pipeline_replay_is_idempotent(full_pipeline, op_repo):
    comm = _create_communication("msg-102", "Please deploy payment service to staging.")

    full_pipeline.process(comm)
    full_pipeline.process(comm)

    open_tasks = op_repo.find_open(item_type=OperationalItemType.TASK)
    assert len(open_tasks) == 1


# -----------------------------------------------------------------------------
# 3. SimpleCognitiveEngine Unified Evidence with OperationsAgent
# -----------------------------------------------------------------------------

def test_cognitive_engine_unifies_operations_agent_evidence(full_pipeline, op_agent, op_repo):
    # Seed an operational item
    item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Complete ISO 27001 audit checklist",
        owner_name="Compliance Officer",
    )
    op_repo.save(item)

    qa = DummyQuestionAnswering()
    engine = SimpleCognitiveEngine(
        pipeline=full_pipeline,
        question_answering=qa,
        operations_agent=op_agent,
    )

    question = Question(text="What is the audit task?")
    answer = engine.ask(question)

    assert answer is not None
    assert "Answered with" in answer.text

    # Direct ask_operations delegation
    op_answer = engine.ask_operations(question)
    assert op_answer is not None
    assert op_answer["question"] == "What is the audit task?"
    assert any("Complete ISO 27001 audit checklist" in ev for ev in op_answer["evidence"])


# -----------------------------------------------------------------------------
# 4. API Route Integration (/ask/operations)
# -----------------------------------------------------------------------------

def test_api_ask_operations_endpoint(op_agent, op_repo):
    item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Renew domain ssl certificates",
        owner_name="DevOps Team",
    )
    op_repo.save(item)

    client = TestClient(app)
    app.dependency_overrides[get_operations_agent] = lambda: op_agent

    try:
        response = client.post(
            "/ask/operations",
            json={"question": "What domain tasks exist?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["question"] == "What domain tasks exist?"
        assert any("Renew domain ssl certificates" in ev for ev in data["evidence"])
        assert "open_task_count" in data["summary"]
    finally:
        app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# 5. Coexistence with Knowledge Agent in Pipeline
# -----------------------------------------------------------------------------

def test_knowledge_and_operations_coexistence_in_pipeline(full_pipeline, op_repo, kn_repo):
    comm = _create_communication("msg-multi-103", "Deployment port is 8080. Deploy payment service.")

    validated = full_pipeline.process(comm)

    # Operations created
    open_tasks = op_repo.find_open(item_type=OperationalItemType.TASK)
    assert len(open_tasks) >= 1

    # Pipeline validated knowledge candidates
    assert len(validated) >= 1


# -----------------------------------------------------------------------------
# 6. ApplicationContainer Wiring
# -----------------------------------------------------------------------------

def test_application_container_operations_agent_wiring(op_agent):
    from application.bootstrap.container import ApplicationContainer
    from unittest.mock import MagicMock

    container = ApplicationContainer(
        engine=MagicMock(),
        knowledge_base_ingestion_service=MagicMock(),
        repository=MagicMock(),
        activity_service=MagicMock(),
        activity_processor=MagicMock(),
        activity_question_service=MagicMock(),
        meeting_transcript_service=MagicMock(),
        meeting_intelligence_service=MagicMock(),
        meeting_transcript_provider=MagicMock(),
        meeting_recording_provider=MagicMock(),
        teams_subscription_repository=MagicMock(),
        teams_subscription_service=MagicMock(),
        teams_recording_subscription_service=MagicMock(),
        reminder_repository=MagicMock(),
        reminder_service=MagicMock(),
        operations_agent=op_agent,
    )
    assert container.operations_agent is op_agent
