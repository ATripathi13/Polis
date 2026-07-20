"""
Base interface for ranking knowledge candidates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.knowledge import (
    KnowledgeCandidate,
)
from domain.reasoning.value_objects.question import (
    Question,
)

class KnowledgeRanker(ABC):
    """
    Ranks knowledge candidates for
    a given question.
    """

    @abstractmethod
    def best_match(
        self,
        question: Question,
        knowledge: list[KnowledgeCandidate],
    ) -> KnowledgeCandidate | None:
        """
        Return the highest-ranked
        knowledge candidate.
        """
        raise NotImplementedError