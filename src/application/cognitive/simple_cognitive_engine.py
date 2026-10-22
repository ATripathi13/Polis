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
        operational_item_service=None,
        knowledge_base_retrieval_service=None,
        knowledge_base_answer_service=None,
        knowledge_agent=None,
        operations_agent=None,
        governance_agent=None,
        meeting_intelligence_service=None,
        calendar_agent=None,
    ) -> None:

        self._pipeline = pipeline

        self._question_answering = (
            question_answering
        )

        self._activity_question_service = (
            activity_question_service
        )

        self._operational_item_service = (
            operational_item_service
        )

        self._knowledge_base_retrieval_service = (
            knowledge_base_retrieval_service
        )

        self._knowledge_base_answer_service = (
            knowledge_base_answer_service
        )

        self._knowledge_agent = knowledge_agent
        self._operations_agent = operations_agent
        self._governance_agent = governance_agent
        self._meeting_intelligence_service = (
            meeting_intelligence_service
        )
        self._calendar_agent = calendar_agent

    @property
    def knowledge_agent(self):
        return self._knowledge_agent

    @property
    def operations_agent(self):
        return self._operations_agent

    @property
    def governance_agent(self):
        return self._governance_agent

    @property
    def calendar_agent(self):
        return self._calendar_agent

    @property
    def meeting_intelligence_service(self):
        return self._meeting_intelligence_service

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

            operational_evidence: list[str] = []

            if self._operations_agent is not None:
                operational_evidence = (
                    self._operations_agent.retrieve_evidence(
                        question,
                    )
                )
            elif self._operational_item_service is not None:
                operational_evidence = (
                    self._operational_item_service.retrieve_evidence(
                        question,
                    )
                )

            knowledge_base_evidence: list[str] = []

            if self._knowledge_agent is not None:
                knowledge_base_evidence = (
                    self._knowledge_agent.retrieve_evidence(
                        question,
                        limit=5,
                    )
                )

            elif (
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

            governance_evidence: list[str] = []

            if self._governance_agent is not None:
                governance_evidence = (
                    self._governance_agent.retrieve_evidence(
                        question,
                    )
                )

            calendar_evidence: list[str] = []

            if self._calendar_agent is not None:
                calendar_evidence = (
                    self._calendar_agent.retrieve_evidence(
                        question,
                    )
                )

            unified_evidence = (
                organizational_evidence
                + operational_evidence
                + knowledge_base_evidence
                + governance_evidence
                + calendar_evidence
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

    def ask_knowledge(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Knowledge Agent directly.
        """
        if self._knowledge_agent is not None:
            return self._knowledge_agent.ask(question)
        return None

    def ask_operations(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Operations Agent directly.
        """
        if self._operations_agent is not None:
            return self._operations_agent.ask(question)
        return None

    def ask_governance(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Governance Agent directly.
        """
        if self._governance_agent is not None:
            return self._governance_agent.ask(question)
        return None

    def ask_calendar(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Calendar Agent directly.
        """
        if self._calendar_agent is not None:
            return self._calendar_agent.ask(question)
        return None

    def summarize_meeting(
        self,
        meeting_id: str,
    ) -> Answer:
        """
        Summarize a meeting via the specialist Meeting Intelligence capability.
        """
        if self._meeting_intelligence_service is not None:
            return self._meeting_intelligence_service.summarize(meeting_id)
        return Answer(
            text="Meeting intelligence service is not configured.",
            confidence=0.0,
            evidence=[],
        )

    def analyze_meeting(
        self,
        meeting_id: str,
    ):
        """
        Produce structured meeting intelligence via the specialist Meeting Intelligence capability.
        """
        if self._meeting_intelligence_service is not None:
            return self._meeting_intelligence_service.analyze(meeting_id)
        raise ValueError("Meeting intelligence service is not configured.")
