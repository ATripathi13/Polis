"""
Simple organizational reasoning service.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from domain.reasoning.value_objects import (
    Answer,
    Question,
)

from .question_answering_service import (
    QuestionAnsweringService,
)

from infrastructure.llm import (
    OpenRouterClient,
)

from datetime import datetime, time
from zoneinfo import ZoneInfo

class SimpleReasoningService(
    QuestionAnsweringService,
):
    """
    Answers questions using persisted organizational
    communication memory.
    """

    def __init__(
        self,
        repository,
        communication_repository,
        llm_client: OpenRouterClient,
        ranker=None,
    ):
        self._ranker = ranker
        self._repository = repository
        self._communication_repository = communication_repository
        self._llm_client = llm_client

    @staticmethod
    def _today_window() -> tuple[datetime, datetime]:
        timezone = ZoneInfo("Asia/Kolkata")

        now = datetime.now(timezone)
        today = now.date()

        start_time = datetime.combine(
            today,
            time.min,
            tzinfo=timezone,
        )

        end_time = start_time + timedelta(days=1)

        return start_time, end_time
        return start_time, end_time

    def _build_retrieval_query(
        self,
        question: Question,
    ) -> str:
        """
        Build the query used for communication retrieval.

        The original question is preserved for the final
        answer generation. When a target person is explicitly
        identified, their name is removed from the retrieval
        query because actor_id already performs the identity
        filtering.
        """

        query = question.text

        target_name = (
            question.target_user_name
            if question.target_user_id is not None
            else None
        )

        if target_name:
            import re

            query = re.sub(
                rf"\b{re.escape(target_name)}\b",
                "",
                query,
                flags=re.IGNORECASE,
            )

        return " ".join(query.split())

    def answer(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question using persisted organizational
        communication events.
        """
        start_time = None
        end_time = None

        question_text = question.text.lower()

        if "today" in question_text:
            start_time, end_time = self._today_window()
        communications = self._communication_repository.search(
            query=self._build_retrieval_query(question),
            limit=20,
            actor_id=(
                question.target_user_id
                if question.target_user_id is not None
                else (
                    question.context.user_id
                    if question.context is not None
                    else None
                )
            ),
            exclude_questions=True,
            start_time=start_time,
            end_time=end_time,
        )

        if "today" in question_text and not communications:
            return Answer(
                text="I don't have enough information to tell what you're working on today.",
                confidence=0.0,
                evidence=[],
            )

        if communications:
            evidence = []

            for communication in communications:
                body = communication.content.body.strip()

                if body:
                    evidence.append(body)

            if evidence:
                context = "\n".join(
                    f"- {item}"
                    for item in evidence
                )

                prompt = f"""
        You are POLIS, an organizational intelligence assistant.

        Answer the user's question using ONLY the organizational
        communications provided below.

        User question:
        {question.text}

        Relevant organizational communications:
        {context}

        Instructions:
        - Answer the question directly.
        - Synthesize multiple relevant communications when necessary.
        - Do not invent facts.
        - Never mention organizational communications, memory, retrieval, evidence, databases, sources, or internal systems.
        - Answer naturally and directly, as POLIS already knows the relevant organizational context.
        - If the evidence does not contain enough information, say so clearly.
        - Keep the answer concise and natural.
        """

                answer_text = self._llm_client.generate(
                    prompt.strip(),
                )

                if answer_text.strip():
                    return Answer(
                        text=answer_text.strip(),
                        confidence=0.8,
                        evidence=evidence,
                    )

        return Answer(
            text=(
                "Sorry, I don't know the answer to that question. "
                "I will keep learning and try to answer it in the future."
            ),
            confidence=0.0,
        )