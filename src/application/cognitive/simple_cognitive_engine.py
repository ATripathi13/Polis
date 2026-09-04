"""
Default implementation of the Polis Cognitive Engine.
"""

from __future__ import annotations

from application.cognitive.cognitive_engine import (
    CognitiveEngine,
)

from application.pipeline.pipeline import (
    PolisPipeline,
)

from domain.reasoning import (
    Question,
    Answer,
    QuestionAnsweringService,
)


class SimpleCognitiveEngine(
    CognitiveEngine,
):
    """
    Default implementation of the
    Polis Cognitive Engine.
    """

    def __init__(
        self,
        pipeline: PolisPipeline,
        question_answering: QuestionAnsweringService,
        activity_question_service=None,
    ) -> None:

        self._pipeline = pipeline

        self._question_answering = (
            question_answering
        )

        self._activity_question_service = (
            activity_question_service
        )

    def learn(
        self,
        communication,
    ) -> None:
        """
        Learn from a communication.
        """

        self._pipeline.process(
            communication,
        )

    def ask(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question.

        Activity-state questions are handled
        by ActivityQuestionService first.

        All other questions continue through
        the existing reasoning service.
        """

        if self._activity_question_service is not None:

            activity_answer = (
                self._activity_question_service.answer(
                    question,
                )
            )

            if activity_answer is not None:
                return activity_answer

        return (
            self._question_answering.answer(
                question,
            )
        )