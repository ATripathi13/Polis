"""
Simple organizational reasoning service.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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


class SimpleReasoningService(
    QuestionAnsweringService,
):
    """
    Answers questions using persisted organizational
    communication memory.
    """

    TIMEZONE = ZoneInfo("Asia/Kolkata")

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

    # ==========================================================
    # DATE / TIME
    # ==========================================================

    @classmethod
    def _date_window(
        cls,
        target_date: date,
    ) -> tuple[datetime, datetime]:
        """
        Return the start and end of a calendar day
        in the organizational timezone.
        """

        start_time = datetime.combine(
            target_date,
            time.min,
            tzinfo=cls.TIMEZONE,
        )

        end_time = start_time + timedelta(days=1)

        return start_time, end_time

    @classmethod
    def _today_window(
        cls,
    ) -> tuple[datetime, datetime]:
        """
        Return today's calendar window.
        """

        now = datetime.now(cls.TIMEZONE)

        return cls._date_window(now.date())

    @classmethod
    def _resolve_date_window(
        cls,
        question_text: str,
    ) -> tuple[datetime | None, datetime | None]:
        """
        Resolve relative and explicit calendar date references.
        """

        now = datetime.now(cls.TIMEZONE)

        normalized = question_text.lower().strip()

        if "today" in normalized:
            return cls._date_window(now.date())

        if "yesterday" in normalized:
            return cls._date_window(
                now.date() - timedelta(days=1)
            )

        explicit_date_patterns = (
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\b",

            r"\b(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+"
            r"(\d{1,2})(?:st|nd|rd|th)?\b",
        )

        for pattern in explicit_date_patterns:
            match = re.search(pattern, normalized)

            if not match:
                continue

            month_names = {
                "january": 1,
                "february": 2,
                "march": 3,
                "april": 4,
                "may": 5,
                "june": 6,
                "july": 7,
                "august": 8,
                "september": 9,
                "october": 10,
                "november": 11,
                "december": 12,
            }

            first, second = match.groups()

            if first.isdigit():
                day = int(first)
                month = month_names[second]
            else:
                month = month_names[first]
                day = int(second)

            year = now.year

            try:
                target_date = date(
                    year,
                    month,
                    day,
                )
            except ValueError:
                return None, None

            return cls._date_window(target_date)

        return None, None

    # ==========================================================
    # RETRIEVAL
    # ==========================================================

    def _build_retrieval_query(
        self,
        question: Question,
    ) -> str:
        """
        Build the semantic query used for communication retrieval.

        Date expressions are handled separately by the date window,
        so they are removed from the retrieval query.

        When a target person is explicitly identified,
        their name is removed because actor_id already performs
        the identity filtering.
        """

        query = question.text

        target_name = (
            question.target_user_name
            if question.target_user_id is not None
            else None
        )

        if target_name:
            query = re.sub(
                rf"\b{re.escape(target_name)}\b",
                "",
                query,
                flags=re.IGNORECASE,
            )

        # Remove explicit calendar date expressions because
        # start_time/end_time already constrain the date.
        query = re.sub(
            r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
            r"(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\b",
            "",
            query,
            flags=re.IGNORECASE,
        )

        query = re.sub(
            r"\b(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+"
            r"\d{1,2}(?:st|nd|rd|th)?\b",
            "",
            query,
            flags=re.IGNORECASE,
        )

        return " ".join(query.split())

    # ==========================================================
    # QUESTION CLASSIFICATION
    # ==========================================================

    @staticmethod
    def _is_working_on_question(
        question_text: str,
    ) -> bool:
        """
        Detect questions asking what a person is working on.
        """

        normalized = " ".join(
            question_text.lower().strip().split()
        )

        patterns = (
            "what am i working on",
            "what am i working on today",
            "what is working on",
            "what is currently working on",
            "what are you working on",
            "what are they working on",
            "what is he working on",
            "what is she working on",
            "what are they working on today",
            "what is he working on today",
            "what is she working on today",
        )

        if any(
            pattern in normalized
            for pattern in patterns
        ):
            return True

        # Covers:
        #
        # What is Akshat working on today?
        # What is Nav working on?
        #
        if re.search(
            r"^what is .+ working on(?: today)?$",
            normalized,
        ):
            return True

        return False

    # ==========================================================
    # LLM RESPONSE VALIDATION
    # ==========================================================

    @staticmethod
    def _is_invalid_llm_response(
        response: str,
    ) -> bool:
        """
        Detect responses that are not actual answers.

        The currently configured OpenRouter free route has
        returned safety metadata such as:

            User Safety: safe

        That must never be exposed to the user as the answer.
        """

        if not response:
            return True

        normalized = " ".join(
            response.strip().split()
        ).lower()

        if not normalized:
            return True

        invalid_exact_responses = {
            "user safety: safe",
            "user safety - safe",
            "user safety safe",
            "safety: safe",
            "safety - safe",
            "safe",
        }

        if normalized in invalid_exact_responses:
            return True

        # Protect against a response where the safety marker
        # appears by itself before/after whitespace.
        if re.fullmatch(
            r"(?:user\s+safety\s*[:\-]\s*)?safe[.!]?",
            normalized,
        ):
            return True

        return False

    # ==========================================================
    # DETERMINISTIC FALLBACK
    # ==========================================================

    @staticmethod
    def _deduplicate_evidence(
        evidence: list[str],
    ) -> list[str]:
        """
        Remove duplicate communication bodies while preserving
        their original order.
        """

        result: list[str] = []
        seen: set[str] = set()

        for item in evidence:
            normalized = " ".join(
                item.lower().split()
            )

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            result.append(item.strip())

        return result

    def _build_working_on_fallback(
        self,
        question: Question,
        evidence: list[str],
    ) -> str:
        """
        Build a deterministic answer for 'working on' questions
        when the LLM returns an unusable response.

        This answer is based only on the retrieved communications.
        """

        evidence = self._deduplicate_evidence(
            evidence
        )

        if not evidence:
            return self._no_information_text(
                question
            )

        person_name = (
            question.target_user_name
            if question.target_user_id is not None
            else None
        )

        # ------------------------------------------------------
        # Extract the work topic from common first-person forms.
        # ------------------------------------------------------

        topics: list[str] = []

        for item in evidence:
            text = item.strip()

            patterns = (
                r"\bi am working on\s+(.+?)(?:[.!?]|$)",
                r"\bworking on\s+(.+?)(?:[.!?]|$)",
                r"\bi'm working on\s+(.+?)(?:[.!?]|$)",
                r"\bi am currently working on\s+(.+?)(?:[.!?]|$)",
                r"\bcurrently working on\s+(.+?)(?:[.!?]|$)",
            )

            for pattern in patterns:
                match = re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )

                if match:
                    topic = match.group(1).strip()

                    if topic:
                        topics.append(topic)

                    break

        topics = self._deduplicate_evidence(
            topics
        )

        if topics:
            topic_text = ", ".join(topics)

            if person_name:
                return (
                    f"{person_name} is working on "
                    f"{topic_text} today."
                )

            return (
                f"You're working on "
                f"{topic_text} today."
            )

        # ------------------------------------------------------
        # If we cannot extract a clean topic, return the actual
        # communication instead of inventing an answer.
        # ------------------------------------------------------

        if person_name:
            return (
                f"{person_name} said: "
                f"\"{evidence[0]}\""
            )

        return (
            f"You said: "
            f"\"{evidence[0]}\""
        )

    @staticmethod
    def _no_information_text(
        question: Question,
    ) -> str:
        """
        Return a target-aware no-information response.
        """

        if question.target_user_id is not None:
            person_name = (
                question.target_user_name
                or "that person"
            )

            return (
                f"I don't have enough information to tell "
                f"what {person_name} is working on today."
            )

        return (
            "I don't have enough information to tell "
            "what you're working on today."
        )

    # ==========================================================
    # MAIN ANSWER
    # ==========================================================

    def answer(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question using persisted organizational
        communication events.
        """

        question_text = (
            question.text.lower().strip()
        )

        # ------------------------------------------------------
        # DATE WINDOW
        # ------------------------------------------------------

        start_time, end_time = (
            self._resolve_date_window(
                question_text
            )
        )

        # ------------------------------------------------------
        # ACTOR FILTER
        # ------------------------------------------------------

        actor_id = None

        if question.target_user_id is not None:
            actor_id = question.target_user_id

        elif question.context is not None:
            actor_id = question.context.user_id

        # ------------------------------------------------------
        # RETRIEVE COMMUNICATIONS
        # ------------------------------------------------------

        retrieval_query = (
            self._build_retrieval_query(
                question
            )
        )

        communications = (
            self._communication_repository.search(
                query=retrieval_query,
                limit=20,
                actor_id=actor_id,
                exclude_questions=True,
                start_time=start_time,
                end_time=end_time,
            )
        )

        # ------------------------------------------------------
        # BUILD EVIDENCE
        # ------------------------------------------------------

        evidence: list[str] = []

        for communication in communications:
            body = (
                communication.content.body.strip()
            )

            if body:
                evidence.append(body)

        evidence = self._deduplicate_evidence(
            evidence
        )

        # ------------------------------------------------------
        # NO DATA
        # ------------------------------------------------------

        if not evidence:
            if (
                "today" in question_text
                and self._is_working_on_question(
                    question_text
                )
            ):
                return Answer(
                    text=self._no_information_text(
                        question
                    ),
                    confidence=0.0,
                    evidence=[],
                )

            return Answer(
                text=(
                    "Sorry, I don't know the answer to "
                    "that question. I will keep learning "
                    "and try to answer it in the future."
                ),
                confidence=0.0,
                evidence=[],
            )

        # ------------------------------------------------------
        # BUILD LLM CONTEXT
        # ------------------------------------------------------

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
- Never mention organizational communications, memory, retrieval, evidence, databases, sources, internal systems, safety checks, or model behavior.
- Never output safety classifications or moderation metadata.
- Do not output labels such as "User Safety: safe".
- Answer naturally and directly, as POLIS already knows the relevant organizational context.
- If the evidence does not contain enough information, say so clearly.
- Keep the answer concise and natural.
- Return ONLY the answer to the user's question.
""".strip()

        # ------------------------------------------------------
        # LLM GENERATION
        # ------------------------------------------------------

        try:
            answer_text = (
                self._llm_client.generate(
                    prompt
                )
            )
        except Exception:
            answer_text = ""

        # ------------------------------------------------------
        # VALID LLM ANSWER
        # ------------------------------------------------------

        if (
            answer_text
            and not self._is_invalid_llm_response(
                answer_text
            )
        ):
            return Answer(
                text=answer_text.strip(),
                confidence=0.8,
                evidence=evidence,
            )

        # ------------------------------------------------------
        # DETERMINISTIC FALLBACK
        #
        # Especially important for:
        #
        # "What is Akshat working on today?"
        #
        # If OpenRouter/free returns:
        #
        # "User Safety: safe"
        #
        # we do NOT send that to Slack.
        # ------------------------------------------------------

        if self._is_working_on_question(
            question_text
        ):
            return Answer(
                text=self._build_working_on_fallback(
                    question,
                    evidence,
                ),
                confidence=0.7,
                evidence=evidence,
            )

        # ------------------------------------------------------
        # GENERIC FALLBACK
        # ------------------------------------------------------

        return Answer(
            text=(
                "I found relevant information, "
                "but I couldn't generate a reliable "
                "answer from it."
            ),
            confidence=0.0,
            evidence=evidence,
        )