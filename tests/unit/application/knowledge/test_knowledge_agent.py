"""
Unit tests for KnowledgeAgent service.
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
from domain.knowledge_base.value_objects import KnowledgeBaseChunk
from application.knowledge.knowledge_agent import KnowledgeAgent


def _create_mock_chunk(content: str, doc_name: str = "handbook.pdf", authority: str = "current_policy"):
    return KnowledgeBaseChunk(
        id="chunk-1",
        document_id="doc-1",
        chunk_index=0,
        content=content,
        qdrant_point_id="point-1",
        metadata={"document_name": doc_name, "authority": authority},
    )


def test_ask_empty_question():
    repo = InMemoryKnowledgeRepository()
    agent = KnowledgeAgent(knowledge_repository=repo)

    result = agent.ask("")
    assert result.status == KnowledgeStatus.MISSING
    assert result.confidence == 0.0
    assert result.missing_aspects == ["empty_question"]


def test_ask_missing_knowledge():
    repo = InMemoryKnowledgeRepository()
    mock_retrieval = MagicMock()
    mock_retrieval.retrieve.return_value = []

    agent = KnowledgeAgent(
        knowledge_repository=repo,
        retrieval_service=mock_retrieval,
    )

    result = agent.ask("What is our quantum computing framework?")
    assert result.status == KnowledgeStatus.MISSING
    assert result.confidence == 0.0
    assert "couldn't find relevant information" in result.answer
    assert len(result.evidence) == 0


def test_ask_grounded_answer_from_knowledge_base():
    repo = InMemoryKnowledgeRepository()
    mock_retrieval = MagicMock()
    chunk = _create_mock_chunk("We use PostgreSQL 15 for data persistence.")
    mock_retrieval.retrieve.return_value = [(chunk, 0.95)]

    mock_answer_service = MagicMock()
    from domain.reasoning.value_objects import Answer
    mock_answer_service.answer.return_value = Answer(
        text="We use PostgreSQL 15 for data persistence.",
        confidence=0.95,
        evidence=[chunk.content],
    )

    agent = KnowledgeAgent(
        knowledge_repository=repo,
        retrieval_service=mock_retrieval,
        answer_service=mock_answer_service,
    )

    result = agent.ask("What database do we use?")
    assert result.status == KnowledgeStatus.KNOWN
    assert result.confidence == 0.95
    assert "PostgreSQL 15" in result.answer
    assert len(result.evidence) == 1
    assert result.sources[0].document_name == "handbook.pdf"
    assert result.sources[0].source_type == "knowledge_base"


def test_ask_detects_contradiction_in_evidence():
    repo = InMemoryKnowledgeRepository()
    mock_retrieval = MagicMock()
    chunk1 = _create_mock_chunk("VPN is required for all remote access.", doc_name="security_policy_2023.pdf")
    chunk2 = _create_mock_chunk("VPN is not required for remote access when using Zero Trust.", doc_name="security_policy_2024.pdf")
    mock_retrieval.retrieve.return_value = [(chunk1, 0.9), (chunk2, 0.88)]

    agent = KnowledgeAgent(
        knowledge_repository=repo,
        retrieval_service=mock_retrieval,
    )

    result = agent.ask("Is VPN required for remote workers?")
    assert result.status == KnowledgeStatus.CONFLICTING
    assert len(result.contradictions) == 1
    assert result.confidence == 0.4
    assert result.contradictions[0].recommended_resolution == "escalate"


def test_ask_detects_uncertainty_gap():
    repo = InMemoryKnowledgeRepository()
    mock_retrieval = MagicMock()
    chunk = _create_mock_chunk("The release date for v2 is tentative and to be decided next month.")
    mock_retrieval.retrieve.return_value = [(chunk, 0.7)]

    agent = KnowledgeAgent(
        knowledge_repository=repo,
        retrieval_service=mock_retrieval,
    )

    result = agent.ask("When is v2 launching?")
    assert result.status == KnowledgeStatus.UNCERTAIN
    assert result.confidence <= 0.5
    assert len(result.missing_aspects) > 0


def test_handle_knowledge_discovered_new_and_idempotent():
    repo = InMemoryKnowledgeRepository()
    agent = KnowledgeAgent(knowledge_repository=repo)

    obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="Our primary coding language is Python.",
        confidence=0.9,
        evidence=["slack_msg_101"],
        metadata={"subject": "coding_language"},
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_DISCOVERED,
        summary="Our primary coding language is Python.",
        confidence=0.9,
        observations=[obs],
    )

    # First discovery
    result1 = agent.process_event(event, source_type="slack", source_event_id="msg_101")
    assert result1 is not None
    assert result1.status == KnowledgeStatus.KNOWN
    assert len(result1.knowledge_changes) == 1
    assert result1.knowledge_changes[0]["action"] == "discovered"

    stored = repo.find("coding_language")
    assert stored is not None
    assert stored.summary == "Our primary coding language is Python."

    # Repeated identical event (Idempotency)
    result2 = agent.process_event(event, source_type="slack", source_event_id="msg_101")
    assert result2 is not None
    assert result2.status == KnowledgeStatus.KNOWN
    assert result2.knowledge_changes == []
    assert len(repo.all()) == 1


def test_handle_knowledge_updated():
    repo = InMemoryKnowledgeRepository()
    # Baseline
    initial_candidate = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="discovered", identifier="database"),
        summary="We use PostgreSQL 14.",
        confidence=0.9,
    )
    repo.save(initial_candidate)

    agent = KnowledgeAgent(knowledge_repository=repo)

    obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="We migrated to PostgreSQL 16.",
        confidence=0.95,
        evidence=["slack_msg_201"],
        metadata={"subject": "database", "authority": "verified"},
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_UPDATED,
        summary="We migrated to PostgreSQL 16.",
        confidence=0.95,
        observations=[obs],
    )

    result = agent.process_event(event, source_type="slack", source_event_id="msg_201")
    assert result is not None
    assert result.status == KnowledgeStatus.UPDATED
    assert len(result.knowledge_changes) == 1
    assert result.knowledge_changes[0]["previous_summary"] == "We use PostgreSQL 14."
    assert result.knowledge_changes[0]["new_summary"] == "We migrated to PostgreSQL 16."

    updated = repo.find("database")
    assert updated.summary == "We migrated to PostgreSQL 16."


def test_handle_knowledge_updated_unverified_authority_rejected():
    repo = InMemoryKnowledgeRepository()
    # High-confidence authoritative policy
    authoritative = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="policy", identifier="expense_limit"),
        summary="Maximum daily meal expense is $50 per official employee handbook.",
        confidence=1.0,
    )
    repo.save(authoritative)

    agent = KnowledgeAgent(knowledge_repository=repo)

    # Low authority unverified message attempting to overwrite
    obs = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="Daily meal expense limit is now $200 according to casual chat.",
        confidence=0.4,
        evidence=["chat_msg_301"],
        metadata={"subject": "expense_limit", "authority": "unverified"},
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.KNOWLEDGE_UPDATED,
        summary="Daily meal expense limit is now $200.",
        confidence=0.4,
        observations=[obs],
    )

    result = agent.process_event(event, source_type="slack", source_event_id="msg_301")
    assert result is not None
    assert result.status == KnowledgeStatus.CONFLICTING
    assert len(result.contradictions) == 1
    assert result.contradictions[0].recommended_resolution == "escalate"

    # Crucial: Authoritative policy was NOT overwritten!
    preserved = repo.find("expense_limit")
    assert preserved.summary == "Maximum daily meal expense is $50 per official employee handbook."


def test_handle_contradiction_detected_event():
    repo = InMemoryKnowledgeRepository()
    agent = KnowledgeAgent(knowledge_repository=repo)

    obs = Observation(
        observation_type=ObservationType.CONTRADICTION,
        summary="Contradiction on release date",
        confidence=0.85,
        evidence=["doc_v1", "doc_v2"],
        metadata={
            "existing_knowledge": "Release date is March 1.",
            "new_knowledge": "Release date is April 15.",
            "conflict_explanation": "Two different release dates published.",
        },
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.CONTRADICTION_DETECTED,
        summary="Contradiction detected: Release date schedule.",
        confidence=0.85,
        observations=[obs],
    )

    result = agent.process_event(event, source_type="docs", source_event_id="doc_1")
    assert result is not None
    assert result.status == KnowledgeStatus.CONFLICTING
    assert len(result.contradictions) == 1
    assert result.contradictions[0].existing_knowledge == "Release date is March 1."
    assert result.contradictions[0].new_knowledge == "Release date is April 15."
    assert result.contradictions[0].recommended_resolution == "escalate"


def test_handle_question_asked_event():
    repo = InMemoryKnowledgeRepository()
    candidate = KnowledgeCandidate(
        subject=KnowledgeSubject(kind="general", identifier="kubernetes"),
        summary="We run EKS in eu-west-1.",
        confidence=0.9,
    )
    repo.save(candidate)

    agent = KnowledgeAgent(knowledge_repository=repo)

    obs = Observation(
        observation_type=ObservationType.QUESTION,
        summary="Where do we run kubernetes?",
        confidence=1.0,
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.QUESTION_ASKED,
        summary="Where do we run kubernetes?",
        confidence=1.0,
        observations=[obs],
    )

    result = agent.process_event(event)
    assert result is not None
    assert result.status == KnowledgeStatus.KNOWN
    assert "eu-west-1" in result.evidence[0]



def test_domain_knowledge_lookup_without_repository_returns_empty():
    agent = KnowledgeAgent(knowledge_repository=None)

    assert agent._find_matching_domain_knowledge("database") == []


def test_domain_knowledge_lookup_ignores_generic_single_word_match():
    repo = InMemoryKnowledgeRepository()
    repo.save(
        KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="project",
                identifier="publishing_calendar",
            ),
            summary="The team is working on the publishing calendar.",
        )
    )
    repo.save(
        KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="infrastructure",
                identifier="database_backup",
            ),
            summary="The database backup runs every night.",
        )
    )
    repo.save(
        KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="operations",
                identifier="server_maintenance",
            ),
            summary="The infrastructure team is working on server maintenance.",
        )
    )

    agent = KnowledgeAgent(knowledge_repository=repo)

    matches = agent._find_matching_domain_knowledge(
        "What am I working on today?"
    )

    assert matches == []


def test_domain_knowledge_lookup_matches_specific_project_terms():
    repo = InMemoryKnowledgeRepository()
    repo.save(
        KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="project",
                identifier="publishing_calendar",
            ),
            summary="The team is working on the publishing calendar.",
        )
    )
    repo.save(
        KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="operations",
                identifier="server_maintenance",
            ),
            summary="The infrastructure team is working on server maintenance.",
        )
    )

    agent = KnowledgeAgent(knowledge_repository=repo)

    matches = agent._find_matching_domain_knowledge(
        "Tell me about the publishing calendar project."
    )

    assert [candidate.subject.identifier for candidate in matches] == [
        "publishing_calendar"
    ]
