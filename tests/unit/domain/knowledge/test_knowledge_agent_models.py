"""
Unit tests for Knowledge Agent domain models and value objects.
"""

from domain.knowledge.enums import KnowledgeStatus
from domain.knowledge.value_objects import (
    KnowledgeContradiction,
    KnowledgeResult,
    KnowledgeSourceReference,
)


def test_knowledge_status_values():
    assert KnowledgeStatus.KNOWN == "known"
    assert KnowledgeStatus.UPDATED == "updated"
    assert KnowledgeStatus.CONFLICTING == "conflicting"
    assert KnowledgeStatus.UNCERTAIN == "uncertain"
    assert KnowledgeStatus.MISSING == "missing"


def test_knowledge_contradiction_creation():
    contradiction = KnowledgeContradiction(
        existing_knowledge="PostgreSQL is the main database.",
        new_knowledge="MongoDB is the main database.",
        conflict_explanation="Opposing database technologies specified.",
        supporting_evidence=["Slack msg 1", "Slack msg 2"],
        authority_info={"source": "engineering_chat"},
        recommended_resolution="escalate",
    )

    assert contradiction.existing_knowledge == "PostgreSQL is the main database."
    assert contradiction.new_knowledge == "MongoDB is the main database."
    assert contradiction.conflict_explanation == "Opposing database technologies specified."
    assert len(contradiction.supporting_evidence) == 2
    assert contradiction.recommended_resolution == "escalate"


def test_knowledge_source_reference():
    source = KnowledgeSourceReference(
        source_type="knowledge_base",
        document_name="architecture_handbook.pdf",
        source_event_id="evt_123",
        authority="current_policy",
        snippet="POLIS utilizes PostgreSQL...",
    )

    assert source.source_type == "knowledge_base"
    assert source.document_name == "architecture_handbook.pdf"
    assert source.source_event_id == "evt_123"
    assert source.authority == "current_policy"
    assert "POLIS utilizes" in source.snippet


def test_knowledge_result_to_answer():
    result = KnowledgeResult(
        status=KnowledgeStatus.KNOWN,
        answer="We use PostgreSQL as our database.",
        confidence=0.9,
        evidence=["Document: architecture.md\nDatabase: PostgreSQL"],
        sources=[
            KnowledgeSourceReference(
                source_type="knowledge_base",
                document_name="architecture.md",
            )
        ],
    )

    assert result.status == KnowledgeStatus.KNOWN
    assert result.confidence == 0.9
    assert len(result.evidence) == 1
    assert len(result.sources) == 1

    answer = result.to_answer()
    assert answer.text == "We use PostgreSQL as our database."
    assert answer.confidence == 0.9
    assert answer.evidence == ["Document: architecture.md\nDatabase: PostgreSQL"]
