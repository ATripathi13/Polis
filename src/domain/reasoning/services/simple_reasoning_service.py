"""
Simple organizational reasoning service.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from domain.reasoning.communication_style import (
    COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS,
    NO_INFORMATION_RESPONSE,
)
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
        identity_resolver=None,
    ):
        self._ranker = ranker
        self._repository = repository
        self._communication_repository = communication_repository
        self._llm_client = llm_client
        self._identity_resolver = identity_resolver

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

        # Strip quoted search terms and exact-phrase expressions when detecting relative date intents
        # so that words like 'today' inside quotes/search text do not trigger current-day filter.
        unquoted = re.sub(
            r'["“][^"”]*["”]|(?<!\w)[\'‘][^\'’]*[\'’](?!\w)',
            '',
            normalized,
        )
        unquoted = re.sub(
            r'\b(?:search\s+(?:the\s+)?)?exact\s+phrase\s*:\s*.*$',
            '',
            unquoted,
        )

        if re.search(r"\btoday\b", unquoted):
            return cls._date_window(now.date())

        if re.search(r"\byesterday\b", unquoted):
            return cls._date_window(
                now.date() - timedelta(days=1)
            )

        explicit_date_patterns = (
            (
                r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
                r"(january|february|march|april|may|june|july|august|"
                r"september|october|november|december)"
                r"(?:\s+(\d{4}))?\b",
                True,
            ),
            (
                r"\b(january|february|march|april|may|june|july|august|"
                r"september|october|november|december)\s+"
                r"(\d{1,2})(?:st|nd|rd|th)?"
                r"(?:,?\s+(\d{4}))?\b",
                False,
            ),
        )

        target_text = unquoted if unquoted.strip() else normalized

        for pattern, day_first in explicit_date_patterns:
            match = re.search(pattern, target_text)

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

            if day_first:
                day_str, month_str, year_str = match.groups()
                day = int(day_str)
                month = month_names[month_str]
            else:
                month_str, day_str, year_str = match.groups()
                month = month_names[month_str]
                day = int(day_str)

            year = int(year_str) if year_str else now.year

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

        # If quoted search text is present, extract it as the core retrieval query.
        quoted_matches = re.findall(
            r'["“]([^"”]+)["”]|(?<!\w)[\'‘]([^\'’]+)[\'’](?!\w)',
            question.text,
        )
        if quoted_matches:
            quoted_phrases = [
                m[0] or m[1] for m in quoted_matches if (m[0] or m[1]).strip()
            ]
            if quoted_phrases:
                return " ".join(p.strip() for p in quoted_phrases)

        # Also support unquoted 'search the exact phrase: ...' or 'exact phrase: ...'
        exact_match = re.search(
            r'\b(?:search\s+(?:the\s+)?)?exact\s+phrase\s*:\s*(.+)$',
            question.text,
            flags=re.IGNORECASE,
        )
        if exact_match:
            return exact_match.group(1).strip()

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
            r"september|october|november|december)"
            r"(?:\s+\d{4})?\b",
            "",
            query,
            flags=re.IGNORECASE,
        )

        query = re.sub(
            r"\b(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+"
            r"\d{1,2}(?:st|nd|rd|th)?"
            r"(?:,?\s+\d{4})?\b",
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

        return NO_INFORMATION_RESPONSE


    @staticmethod
    def _is_raw_slack_id(value: str | None) -> bool:
        """
        Check whether a string is a raw Slack user identifier or mention
        rather than a human-readable display name.
        """
        if not value:
            return False
        cleaned = value.strip()
        if re.fullmatch(r"[UW][A-Z0-9]{8,12}", cleaned):
            return True
        if re.fullmatch(r"<@[UW][A-Z0-9]{8,12}(?:\|[^>]+)?>", cleaned):
            return True
        if re.fullmatch(r"user\s+[UW][A-Z0-9]{8,12}", cleaned, re.IGNORECASE):
            return True
        return False

    @classmethod
    def _format_actor(
        cls,
        actor: Any,
        identity_resolver: Any = None,
    ) -> str | None:
        """
        Format an actor's display name and stable ID for evidence grounding.
        Handles missing or unknown actors safely without inventing identities.
        Ensures raw Slack IDs are never presented as human-readable display names.
        """
        if actor is None:
            return None

        display_name: str | None = None
        internal_id: str | None = None

        if isinstance(actor, dict):
            name_val = actor.get("display_name")
            if isinstance(name_val, str) and name_val.strip():
                display_name = name_val.strip()

            ident_val = actor.get("identity")
            if isinstance(ident_val, dict):
                id_val = ident_val.get("internal_id")
                if isinstance(id_val, str) and id_val.strip():
                    internal_id = id_val.strip()
            elif hasattr(ident_val, "internal_id"):
                id_val = getattr(ident_val, "internal_id")
                if isinstance(id_val, str) and id_val.strip():
                    internal_id = id_val.strip()
        else:
            name_val = getattr(actor, "display_name", None)
            if isinstance(name_val, str) and name_val.strip():
                display_name = name_val.strip()

            ident_val = getattr(actor, "identity", None)
            if ident_val is not None:
                if isinstance(ident_val, dict):
                    id_val = ident_val.get("internal_id")
                    if isinstance(id_val, str) and id_val.strip():
                        internal_id = id_val.strip()
                else:
                    id_val = getattr(ident_val, "internal_id", None)
                    if isinstance(id_val, str) and id_val.strip():
                        internal_id = id_val.strip()

        # If display_name is a valid human name (not a raw Slack ID and not identical to internal ID), use it
        if display_name and not cls._is_raw_slack_id(display_name) and display_name != internal_id:
            return display_name

        # If display_name was missing or was a raw Slack ID, attempt resolution via identity_resolver if provided
        target_id_for_resolution = internal_id or (display_name if cls._is_raw_slack_id(display_name) else None)
        if identity_resolver is not None and target_id_for_resolution and hasattr(identity_resolver, "get_display_name"):
            try:
                resolved = identity_resolver.get_display_name(target_id_for_resolution)
                if resolved and not cls._is_raw_slack_id(resolved) and resolved != target_id_for_resolution:
                    return resolved.strip()
            except Exception:
                pass

        # If internal_id is available and is NOT a raw Slack user ID (e.g. non-Slack test mock or name), use it
        if internal_id and not cls._is_raw_slack_id(internal_id):
            return internal_id

        # Never treat a raw Slack ID as a human-readable display name
        return None

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

            lines = [
                f"Communication time: "
                f"{created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            ]

            sender = self._format_actor(
                getattr(communication, "actor", None),
                identity_resolver=self._identity_resolver,
            )
            if sender:
                lines.append(f"Sender: {sender}")

            lines.append(f"Message: {body}")

            evidence.append("\n".join(lines))

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

Shared communication style:
{COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS}

Additional instructions:
- For greetings, broad capability questions, and casual requests, answer in 2-4 short sentences.
- Never respond to a simple question with a catalogue of every capability, project, task, or tool.
- For ambiguous follow-up requests, ask one concise clarifying question instead of listing unrelated pending work.
- For status questions, summarize only the most relevant current work, blockers, and next steps supported by the evidence.
- Interpret relative time expressions such as yesterday, today, tomorrow, recently, earlier, or last week using the current organizational date/time and the timestamps attached to the relevant information.
- Speak naturally in the first person as a helpful, thoughtful teammate (using "I", "I'll", "I've", "don't", "can't").
- Use simple, familiar everyday English instead of corporate or technical jargon.
- Prefer short, clear sentences.
- Answer the user's question directly without unnecessary introductions, preamble, or repetitive greetings.
- Sound friendly, calm, confident, and professional without sounding stiff or robotic.
- Do not overuse "I" — use it naturally, not in every sentence.
- If technical terms are necessary, explain them in plain English.
- Determine which provided information is actually relevant to the user's question.
- Synthesize multiple pieces of information when necessary.
- Information may describe people, responsibilities, projects, current work, processes, or other organizational context.
- When a document name or explicit identity identifies a person, use that identity when associating the information with them.
- Do not invent facts.
- Do not assume information that is not present.
- Distinguish general responsibilities and recurring duties from specific current activities.
- Do not treat a job responsibility, profile description, expected outcome, recurring duty, or generic statement such as "daily tasks" as proof that the person is doing that work today.
- For time-specific questions, only state an activity as current when the provided knowledge explicitly supports that activity for the requested time period.
- When the knowledge does not establish a time-specific activity, answer that you don't have enough information to determine it. Do not explain what documents or knowledge contain.
- If the knowledge does not contain enough information to answer confidently, clearly admit uncertainty in plain first person (e.g., "I don't have enough information to answer that confidently. Can you share a little more?").
- Never mention documents, provided information, evidence, sources, retrieval, embeddings, databases, memory, internal systems, prompts, or model behavior.
- Do not use stiff source-referencing language such as "based on the provided information", "the documents say", or "according to the records". Natural phrases such as "I found..." or "I don't have..." are welcome.
- Never output safety classifications or moderation metadata.
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

Shared communication style:
{COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS}

Additional instructions:
- For greetings, broad capability questions, and casual requests, answer in 2-4 short sentences.
- Never respond to a simple question with a catalogue of every capability, project, task, or tool.
- For ambiguous follow-up requests, ask one concise clarifying question instead of listing unrelated pending work.
- For status questions, summarize only the most relevant current work, blockers, and next steps supported by the evidence.
- Speak naturally in the first person as a helpful, thoughtful teammate (using "I", "I'll", "I've", "don't", "can't").
- Use simple, familiar everyday English instead of corporate or technical jargon.
- Prefer short, clear sentences.
- Answer the user's question directly without unnecessary introductions, preamble, or repetitive greetings.
- Sound friendly, calm, confident, and professional without sounding stiff or robotic.
- Do not overuse "I" — use it naturally, not in every sentence.
- Synthesize multiple relevant communications when necessary.
- Do not invent facts.
- If the communications do not contain enough information to answer confidently, clearly admit uncertainty in plain first person (e.g., "I don't have enough information to answer that confidently. Can you share a little more?").
- Never mention organizational communications, memory, retrieval, evidence, databases, sources, internal systems, safety checks, or model behavior.
- Never output safety classifications or moderation metadata.
- Do not output labels such as "User Safety: safe".
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
