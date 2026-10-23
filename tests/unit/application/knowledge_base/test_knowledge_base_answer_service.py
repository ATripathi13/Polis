"""
Unit tests for KnowledgeBaseAnswerService.
"""

from unittest.mock import MagicMock
from domain.knowledge_base import KnowledgeBaseChunk
from domain.reasoning.value_objects import Answer
from application.knowledge_base.knowledge_base_answer_service import (
    KnowledgeBaseAnswerService,
)


def _make_chunk(content: str, doc_name: str = "handbook.md") -> KnowledgeBaseChunk:
    return KnowledgeBaseChunk(
        id="chunk-1",
        document_id="doc-1",
        chunk_index=0,
        content=content,
        qdrant_point_id="point-1",
        metadata={"document_name": doc_name, "authority": "current_policy"},
    )


def test_answer_empty_question():
    llm = MagicMock()
    service = KnowledgeBaseAnswerService(llm_client=llm)

    ans = service.answer("   ", results=[(_make_chunk("Content"), 0.9)])
    assert ans.confidence == 0.0
    assert ans.text == "Please provide a question."
    assert ans.evidence == []
    llm.generate.assert_not_called()


def test_answer_empty_results():
    llm = MagicMock()
    service = KnowledgeBaseAnswerService(llm_client=llm)

    ans = service.answer("What is our leave policy?", results=[])
    assert ans.confidence == 0.0
    assert "couldn't find relevant information" in ans.text
    assert ans.evidence == []
    llm.generate.assert_not_called()


def test_answer_grounded_success():
    llm = MagicMock()
    llm.generate.return_value = "Employees receive 25 days of paid annual leave."
    service = KnowledgeBaseAnswerService(llm_client=llm)

    chunk = _make_chunk("Annual leave entitlement is 25 days per calendar year.")
    results = [(chunk, 0.92)]

    ans = service.answer("How many days of annual leave do employees get?", results)
    assert ans.confidence == 0.8
    assert ans.text == "Employees receive 25 days of paid annual leave."
    assert len(ans.evidence) == 1
    assert chunk.content in ans.evidence

    llm.generate.assert_called_once()
    prompt = llm.generate.call_args[0][0]
    assert "Annual leave entitlement is 25 days" in prompt
    assert "handbook.md" in prompt
    assert "Answer the user's question using ONLY the Knowledge Base" in prompt


def test_answer_llm_failure_returns_ungrounded_fallback():
    llm = MagicMock()
    llm.generate.side_effect = RuntimeError("OpenRouter API timeout")
    service = KnowledgeBaseAnswerService(llm_client=llm)

    chunk = _make_chunk("Some policy text.")
    results = [(chunk, 0.85)]

    ans = service.answer("What is the policy?", results)
    assert ans.confidence == 0.0
    assert "couldn't generate a reliable answer" in ans.text
    assert len(ans.evidence) == 1
    assert ans.evidence[0] == "Some policy text."


def test_answer_llm_empty_response():
    llm = MagicMock()
    llm.generate.return_value = "   "
    service = KnowledgeBaseAnswerService(llm_client=llm)

    chunk = _make_chunk("Some policy text.")
    results = [(chunk, 0.85)]

    ans = service.answer("What is the policy?", results)
    assert ans.confidence == 0.0
    assert "couldn't generate a reliable answer" in ans.text
