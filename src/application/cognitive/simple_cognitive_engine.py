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
    ) -> None:

        self._pipeline = pipeline

        self._question_answering = (
            question_answering
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
        """

        return (
            self._question_answering.answer(
                question,
            )
        )