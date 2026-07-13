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


class SimpleReasoningService(
    QuestionAnsweringService,
):
    """
    Answers questions using
    organizational knowledge.
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
    ) -> None:

        self._repository = repository

    def answer(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question using validated
        organizational knowledge.
        """

        normalized = question.text.lower()

        for candidate in self._repository.all():

            subject = (
                candidate.subject.identifier.lower()
            )

            if subject in normalized:

                return Answer(
                    text=candidate.summary,
                    confidence=candidate.confidence,
                    evidence=[
                        event.summary
                        for event in candidate.supporting_events
                    ],
                )

        return Answer(
            text="I don't know.",
            confidence=0.0,
        )