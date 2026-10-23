"""
Targeted regression and edge case verification tests for KnowledgeAgent.
"""

from unittest.mock import MagicMock
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
from domain.reasoning.value_objects import Question
from domain.knowledge_base.value_objects import KnowledgeBaseChunk
from application.knowledge.knowledge_agent import KnowledgeAgent


def test_ask_and_retrieve_with_none_question():
    repo = InMemoryKnowledgeRepository()
    agent = KnowledgeAgent(knowledge_repository=repo)

    # Calling ask(None)
    result = agent.ask(None)
    assert result.status == KnowledgeStatus.MISSING
    assert result.confidence == 0.0
    assert result.missing_aspects == ["empty_question"]
    assert result.evidence == []

    # Calling retrieve_evidence(None)
    evidence = agent.retrieve_evidence(None)
    assert evidence == []


def test_knowledge_discovered_delegates_to_update_and_rejects_unauthorized_overwrite():
    """
    Regression test: When a KNOWLEDGE_DISCOVERED event arrives for an existing subject
    with a changed summary from an unverified source, it must not silently overwrite
    authoritative knowledge. It must be evaluated under authority rules and rejected as CONFLICTING.
    """
    repo = InMemoryKnowledgeRepository()
    authoritative = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="infrastructure", identifier="primary_database"),
        summary="PostgreSQL 16 in multi-AZ setup with automatic failover.",
        confidence=1.0,
    )
    repo.save(authoritative)

    agent = KnowledgeAgent(knowledge_repository=repo)

    # Low-authority unverified event attempting to overwrite via KNOWLEDGE_DISCOVERED
    obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="We run SQLite in production on single server.",
        confidence=0.3,
        evidence=["rumor_chat_1"],
        metadata={"subject": "primary_database", "authority": "unverified"},
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_DISCOVERED,
        summary="We run SQLite in production on single server.",
        confidence=0.3,
        observations=[obs],
    )

    result = agent.process_event(event, source_type="slack", source_event_id="rumor_1")

    assert result is not None
    assert result.status == KnowledgeStatus.CONFLICTING
    assert len(result.contradictions) == 1
    assert result.contradictions[0].recommended_resolution == "escalate"

    # Crucial assertion: Authoritative knowledge is intact!
    stored = repo.find("primary_database")
    assert stored is not None
    assert stored.summary == "PostgreSQL 16 in multi-AZ setup with automatic failover."


def test_plural_copula_contradiction_detection():
    repo = InMemoryKnowledgeRepository()
    mock_retrieval = MagicMock()

    chunk1 = KnowledgeBaseChunk(
        id="c1",
        document_id="doc1",
        chunk_index=0,
        content="Hardware tokens are required for all employees.",
        qdrant_point_id="p1",
        metadata={"document_name": "sec1.md"},
    )
    chunk2 = KnowledgeBaseChunk(
        id="c2",
        document_id="doc2",
        chunk_index=0,
        content="Hardware tokens are not required if software OTP is active.",
        qdrant_point_id="p2",
        metadata={"document_name": "sec2.md"},
    )

    mock_retrieval.retrieve.return_value = [(chunk1, 0.9), (chunk2, 0.88)]

    agent = KnowledgeAgent(
        knowledge_repository=repo,
        retrieval_service=mock_retrieval,
    )

    result = agent.ask("Are hardware tokens required?")
    assert result.status == KnowledgeStatus.CONFLICTING
    assert len(result.contradictions) == 1
    assert "required" in result.contradictions[0].conflict_explanation


def test_agent_with_none_repository_graceful():
    agent = KnowledgeAgent(knowledge_repository=None)

    # Should not raise AttributeError on None repository
    result = agent.ask("What is our architecture?")
    assert result.status == KnowledgeStatus.MISSING
    assert result.confidence == 0.0

    evidence = agent.retrieve_evidence("What is our architecture?")
    assert evidence == []

    all_known = agent.get_known_knowledge()
    assert all_known == []

    known = agent.get_known_knowledge("architecture")
    assert known == []


def test_ask_target_user_forwarded_to_retrieval():
    repo = InMemoryKnowledgeRepository()
    mock_retrieval = MagicMock()
    mock_retrieval.retrieve.return_value = []

    agent = KnowledgeAgent(
        knowledge_repository=repo,
        retrieval_service=mock_retrieval,
    )

    # Passing via employee_slack_user_id keyword
    agent.ask("What is my PTO balance?", employee_slack_user_id="U_ALICE")
    mock_retrieval.retrieve.assert_called_with(
        "What is my PTO balance?",
        limit=5,
        employee_slack_user_id="U_ALICE",
    )

    # Passing via Question object
    q = Question(text="What is my PTO balance?", target_user_id="U_BOB")
    agent.ask(q)
    mock_retrieval.retrieve.assert_called_with(
        "What is my PTO balance?",
        limit=5,
        employee_slack_user_id="U_BOB",
    )


def test_get_known_knowledge_filtering_and_limits():
    repo = InMemoryKnowledgeRepository()
    c1 = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="tech", identifier="k8s_cluster"),
        summary="Kubernetes cluster in AWS",
    )
    c2 = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="tech", identifier="docker_runtime"),
        summary="Containerd runtime with Docker buildx",
    )
    c3 = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="policy", identifier="vacation_days"),
        summary="25 annual vacation days",
    )
    repo.save(c1)
    repo.save(c2)
    repo.save(c3)

    agent = KnowledgeAgent(knowledge_repository=repo)

    # Filter by topic "kubernetes"
    k8s = agent.get_known_knowledge(topic="kubernetes")
    assert len(k8s) == 1
    assert k8s[0].subject.identifier == "k8s_cluster"

    # All with limit 2
    all_limited = agent.get_known_knowledge(limit=2)
    assert len(all_limited) == 2
