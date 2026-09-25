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
        knowledge_base_retrieval_service=None,
        knowledge_base_answer_service=None,
    ) -> None:

        self._pipeline = pipeline

        self._question_answering = (
            question_answering
        )

        self._activity_question_service = (
            activity_question_service
        )

        self._knowledge_base_retrieval_service = (
            knowledge_base_retrieval_service
        )

        self._knowledge_base_answer_service = (
            knowledge_base_answer_service
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

        Routing order:

        1. Activity-state questions
        2. Knowledge Base questions
           when semantic similarity is high enough
        3. Existing organizational reasoning
        """

        if self._activity_question_service is not None:

            activity_answer = (
                self._activity_question_service.answer(
                    question,
                )
            )

            if activity_answer is not None:
                return activity_answer

        if (
            self._knowledge_base_retrieval_service is not None
            and self._knowledge_base_answer_service is not None
        ):

            knowledge_results = (
                self._knowledge_base_retrieval_service.retrieve(
                    question.text,
                    limit=5,
                )
            )

            if knowledge_results:

                top_score = knowledge_results[0][1]

                if top_score >= 0.70:

                    return (
                        self._knowledge_base_answer_service.answer(
                            question.text,
                            knowledge_results,
                        )
                    )

        return (
            self._question_answering.answer(
                question,
            )
        )