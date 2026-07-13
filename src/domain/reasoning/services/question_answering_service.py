"""
Base question answering service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.reasoning.value_objects import (
    Answer,
    Question,
)


class QuestionAnsweringService(ABC):
    """
    Base interface for answering
    questions from organizational knowledge.
    """

    @abstractmethod
    def answer(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question.
        """
        raise NotImplementedError