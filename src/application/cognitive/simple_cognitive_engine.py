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
        2. Unified organizational evidence
           - organizational communications
           - Knowledge Base documents
        3. Existing organizational reasoning fallback

        The final answer is generated from the combined evidence
        so the LLM can determine which knowledge is relevant
        instead of using hardcoded question classification.
        """

        # ------------------------------------------------------
        # ACTIVITY QUESTIONS
        # ------------------------------------------------------

        if self._activity_question_service is not None:

            activity_answer = (
                self._activity_question_service.answer(
                    question,
                )
            )

            if activity_answer is not None:
                return activity_answer

        # ------------------------------------------------------
        # UNIFIED EVIDENCE
        # ------------------------------------------------------

        retrieve_evidence = getattr(
            self._question_answering,
            "retrieve_evidence",
            None,
        )

        answer_from_evidence = getattr(
            self._question_answering,
            "answer_from_evidence",
            None,
        )

        if (
            callable(retrieve_evidence)
            and callable(answer_from_evidence)
        ):

            organizational_evidence = (
                retrieve_evidence(
                    question,
                )
            )

            knowledge_base_evidence: list[str] = []

            if (
                self._knowledge_base_retrieval_service
                is not None
            ):

                knowledge_results = (
                    self._knowledge_base_retrieval_service.retrieve(
                        question.text,
                        limit=5,
                        employee_slack_user_id=(
                            question.target_user_id
                        ),
                    )
                )

                for chunk, _score in knowledge_results:

                    content = (
                        chunk.content.strip()
                    )

                    if not content:
                        continue

                    document_name = (
                        chunk.metadata.get(
                            "document_name",
                            "Unknown",
                        )
                    )

                    knowledge_base_evidence.append(
                        (
                            f"Knowledge Base document: "
                            f"{document_name}\n"
                            f"{content}"
                        )
                    )

            unified_evidence = (
                organizational_evidence
                + knowledge_base_evidence
            )

            if unified_evidence:

                return answer_from_evidence(
                    question,
                    unified_evidence,
                    fallback_evidence=(
                        organizational_evidence
                    ),
                )

        # ------------------------------------------------------
        # EXISTING REASONING FALLBACK
        # ------------------------------------------------------

        return self._question_answering.answer(
            question,
        )