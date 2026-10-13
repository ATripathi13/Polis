"""
Represents a structured result produced by the Knowledge Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject
from domain.reasoning.value_objects import Answer
from ..enums.knowledge_status import KnowledgeStatus
from .knowledge_contradiction import KnowledgeContradiction
from .knowledge_source_reference import KnowledgeSourceReference


@dataclass(frozen=True, slots=True)
class KnowledgeResult(ValueObject):
    """
    Structured outcome of Knowledge Agent intelligence evaluation,
    retrieval, reasoning, and event processing.
    """

    status: KnowledgeStatus
    answer: str
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)
    sources: list[KnowledgeSourceReference] = field(default_factory=list)
    contradictions: list[KnowledgeContradiction] = field(default_factory=list)
    knowledge_changes: list[dict[str, Any]] = field(default_factory=list)
    missing_aspects: list[str] = field(default_factory=list)

    def to_answer(self) -> Answer:
        """
        Convert to standard domain Answer representation for POLIS.
        """
        return Answer(
            text=self.answer,
            confidence=self.confidence,
            evidence=self.evidence,
        )
