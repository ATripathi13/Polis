"""
Integration tests for KnowledgeAgent specialist integration with POLIS pipeline,
cognitive engine, and API endpoints.
"""

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from application.cognitive import SimpleCognitiveEngine
from application.knowledge import KnowledgeAgent
from application.pipeline.pipeline import PolisPipeline
from domain.knowledge.enums import KnowledgeStatus
from domain.knowledge.repositories import InMemoryKnowledgeRepository
from domain.knowledge.value_objects import (
    KnowledgeCandidate,
    KnowledgeSubject,
)
from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from domain.observation import (
    Observation,
    ObservationType,
)
from domain.reasoning import Question, Answer
from interfaces.api.app import app
from interfaces.api.dependencies import get_cognitive_engine, get_knowledge_agent


def test_pipeline_dispatches_events_to_knowledge_agent():
    repo = InMemoryKnowledgeRepository()
    agent = MagicMock(wraps=KnowledgeAgent(knowledge_repository=repo))

    mock_obs_extractor = MagicMock()
    mock_org_builder = MagicMock()
    mock_k_builder = MagicMock()
    mock_k_validator = MagicMock()
    mock_k_acceptor = MagicMock()
    mock_reasoning = MagicMock()

    obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="Authentication is handled via OAuth2.",
        confidence=0.92,
        evidence=["teams_msg_44"],
        metadata={"subject": "auth_system"},
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_DISCOVERED,
        summary="Authentication is handled via OAuth2.",
        confidence=0.92,
        observations=[obs],
    )

    mock_obs_extractor.extract.return_value = [obs]
    mock_org_builder.build.return_value = [event]
    mock_k_builder.build.return_value = []

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=mock_obs_extractor,
        organization_builder=mock_org_builder,
        knowledge_builder=mock_k_builder,
        knowledge_validator=mock_k_validator,
        knowledge_acceptance_service=mock_k_acceptor,
        reasoning_service=mock_reasoning,
        knowledge_agent=agent,
    )

    comm = MagicMock()
    comm.source.value = "teams"
    comm.source_event_id = "teams_msg_44"

    pipeline.process(comm)

    agent.process_event.assert_called_once_with(
        event,
        source_type="teams",
        source_event_id="teams_msg_44",
        persist=False,
    )

def test_cognitive_engine_unifies_knowledge_agent_evidence():
    repo = InMemoryKnowledgeRepository()
    candidate = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="general", identifier="redis_cache"),
        summary="Redis cluster is used for session caching in production.",
        confidence=0.9,
    )
    repo.save(candidate)

    agent = KnowledgeAgent(knowledge_repository=repo)

    mock_qa = MagicMock()
    mock_qa.retrieve_evidence.return_value = []
    mock_qa.answer_from_evidence.side_effect = lambda q, ev, **kw: Answer(
        text="Redis cluster is used for session caching.",
        confidence=0.9,
        evidence=ev,
    )

    engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=mock_qa,
        knowledge_agent=agent,
    )

    assert engine.knowledge_agent is agent

    answer = engine.ask(Question(text="What do we use for session caching?"))
    assert "Redis cluster" in answer.text
    assert len(answer.evidence) > 0
    assert "session caching" in answer.evidence[0]


def test_ask_api_routes_with_knowledge_agent():
    repo = InMemoryKnowledgeRepository()
    candidate = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="general", identifier="cloud_provider"),
        summary="Our primary cloud provider is AWS.",
        confidence=0.95,
    )
    repo.save(candidate)

    agent = KnowledgeAgent(knowledge_repository=repo)

    mock_engine = MagicMock()
    mock_engine.ask.return_value = Answer(
        text="Our primary cloud provider is AWS.",
        confidence=0.95,
        evidence=["Document: infra.md\nCloud: AWS"],
    )

    app.dependency_overrides[get_cognitive_engine] = lambda: mock_engine
    app.dependency_overrides[get_knowledge_agent] = lambda: agent

    try:
        client = TestClient(app)

        # Standard /ask endpoint
        res = client.post("/ask", json={"question": "Which cloud provider do we use?"})
        assert res.status_code == 200
        data = res.json()
        assert data["answer"] == "Our primary cloud provider is AWS."

        # Direct /ask/knowledge intelligence endpoint
        res_k = client.post("/ask/knowledge", json={"question": "Which cloud provider do we use?"})
        assert res_k.status_code == 200
        data_k = res_k.json()
        assert data_k["status"] == "known"
        assert "AWS" in data_k["answer"]
        assert data_k["confidence"] >= 0.7
        assert len(data_k["sources"]) > 0

        # /ask/knowledge with non-existent knowledge
        res_missing = client.post("/ask/knowledge", json={"question": "What is our spaceship fuel?"})
        assert res_missing.status_code == 200
        data_m = res_missing.json()
        assert data_m["status"] == "missing"
        assert data_m["confidence"] == 0.0

    finally:
        app.dependency_overrides.clear()
