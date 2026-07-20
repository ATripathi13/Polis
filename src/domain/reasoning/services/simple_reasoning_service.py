"""
Simple rule-based reasoning service.
"""

from __future__ import annotations

from domain.knowledge import (
    KnowledgeRepository,
)

from .question_answering_service import (
    QuestionAnsweringService,
)

from domain.reasoning.value_objects import (
    Answer,
    Question,
)

from domain.reasoning.rankers import (
    KnowledgeRanker,
)

class SimpleReasoningService(
    QuestionAnsweringService,
):
    """
    Answers questions using
    organizational knowledge.
    """

    def __init__(
        self,
        repository,
        ranker: KnowledgeRanker,
    ):
        self._ranker = ranker
        self._repository = repository

    def answer(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question using validated
        organizational knowledge.
        """

        candidate = self._ranker.best_match(
            question=question,
            knowledge=self._repository.all(),
        )

        if candidate is not None:
            return Answer(
                text=candidate.summary,
                confidence=candidate.confidence,
                evidence=[
                    event.summary
                    for event in candidate.supporting_events
                ],
            )

        return Answer(
            text="Sorry, I don't know the answer to that question. I will keep learning and try to answer it in the future.",
            confidence=0.0,
        )