"""
Simple organizational reasoning service.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
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
        # Remove explicit Slack user mentions because
        # actor_id already performs the identity filtering.
        query = re.sub(
            r"<@[A-Z0-9]+(?:\|[^>]+)?>",
            "",
            query,
        )
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


    @staticmethod
    def _no_information_text(
        question: Question,
    ) -> str:
        """
        Return a generic no-information response.
        """

        return (
            "POLIS does not have enough information "
            "to answer that question."
        )

    def retrieve_evidence(
        self,
        question: Question,
    ) -> list[str]:
        """
        Retrieve relevant organizational communication evidence
        without generating a final answer.
        """

        question_text = (
            question.text.lower().strip()
        )

        start_time, end_time = (
            self._resolve_date_window(
                question_text
            )
        )

        actor_id = None

        if question.target_user_id is not None:
            actor_id = question.target_user_id

        elif question.context is not None:
            actor_id = question.context.user_id

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

        evidence: list[str] = []

        for communication in communications:
            body = communication.content.body.strip()

            if not body:
                continue

            created_at = communication.created_at

            if created_at.tzinfo is None:
                created_at = created_at.replace(
                    tzinfo=timezone.utc
                )

            created_at = created_at.astimezone(
                self.TIMEZONE
            )

            evidence.append(
                (
                    f"Communication time: "
                    f"{created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                    f"Message: {body}"
                )
            )

        return self._deduplicate_evidence(
            evidence
        )

    def answer_from_evidence(
        self,
        question: Question,
        evidence: list[str],
        *,
        fallback_evidence: list[str] | None = None,
    ) -> Answer:
        """
        Generate a grounded answer from unified evidence.

        Evidence may come from organizational communications,
        Knowledge Base documents, or both.
        """

        evidence = self._deduplicate_evidence(
            evidence
        )

        if not evidence:
            return Answer(
                text=self._no_information_text(
                    question
                ),
                confidence=0.0,
                evidence=[],
            )

        context = "\n".join(
            f"- {item}"
            for item in evidence
        )
        current_time = datetime.now(
            self.TIMEZONE
        ).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )

        prompt = f"""
You are POLIS, an organizational intelligence assistant.

Answer the user's question using ONLY the relevant
organizational knowledge provided below.

User question:
{question.text}

Current organizational date and time:
{current_time}

Relevant organizational knowledge:
{context}

Instructions:
- Interpret relative time expressions such as yesterday, today, tomorrow, recently, earlier, or last week using the current organizational date/time and the timestamps attached to the relevant information.
- Answer the question directly.
- Determine which provided information is actually relevant
  to the user's question.
- Synthesize multiple pieces of information when necessary.
- Information may describe people, responsibilities,
  projects, current work, processes, or other organizational
  context.
- When a document name or explicit identity identifies a person,
  use that identity when associating the information with them.
- Do not invent facts.
- Do not assume information that is not present.
- Distinguish general responsibilities and recurring duties
  from specific current activities.
- Do not treat a job responsibility, profile description,
  expected outcome, recurring duty, or generic statement such
  as "daily tasks" as proof that the person is doing that work
  today.
- For time-specific questions, only state an activity as current
  when the provided knowledge explicitly supports that activity
  for the requested time period.
- When the knowledge does not establish a time-specific activity,
  answer only that POLIS does not have enough information to
  determine it. Do not explain what the documents or knowledge
  contain.
- Never mention documents, provided information, evidence,
  sources, retrieval, embeddings, databases, memory,
  internal systems, or model behavior.
- Do not say phrases such as "based on the provided information",
  "the documents say", "I found", "the available information",
  or similar source-referencing language.
- If the knowledge does not establish the answer, simply state
  that POLIS does not have enough information to answer.
- Never output safety classifications or moderation metadata.
- Keep the answer concise and natural.
- If the provided information is insufficient, say so clearly.
- Return ONLY the answer.
""".strip()

        try:
            answer_text = (
                self._llm_client.generate(
                    prompt
                )
            )
        except Exception:
            answer_text = ""

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

        return Answer(
            text=(
                "I found relevant information, "
                "but I couldn't generate a reliable "
                "answer from it."
            ),
            confidence=0.0,
            evidence=evidence,
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
            return Answer(
                text=self._no_information_text(question),
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