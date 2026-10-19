from __future__ import annotations

import json

from domain.meetings.repositories.meeting_transcript_repository import (
    MeetingTranscriptRepository,
)
from domain.reasoning.value_objects import Answer
from domain.organization.repositories.organization_event_repository import (
    OrganizationEventRepository,
)
from infrastructure.llm import OpenRouterClient

from application.meetings.meeting_intelligence_result import (
    MeetingIntelligenceResult,
)


class MeetingIntelligenceService:
    """
    Provides AI intelligence over persisted meeting transcripts.
    """

    MAX_CONTEXT_CHARS = 24000

    def __init__(
        self,
        *,
        transcript_repository: MeetingTranscriptRepository,
        llm_client: OpenRouterClient,
        organization_event_repository: OrganizationEventRepository | None = None,
    ) -> None:
        self._transcript_repository = transcript_repository
        self._llm_client = llm_client
        self._organization_event_repository = organization_event_repository

    def analyze(
        self,
        meeting_id: str,
    ) -> MeetingIntelligenceResult:
        transcripts = self._transcript_repository.find_by_meeting_id(meeting_id)

        if not transcripts:
            raise ValueError("Meeting transcript not found.")

        context_parts = []
        transcript_ids = set()

        for transcript in transcripts:
            text = transcript.transcript.strip()
            if text:
                context_parts.append(text)

            transcript_id = transcript.metadata.get("transcript_id")
            if transcript_id:
                transcript_ids.add(str(transcript_id))

            business_id = getattr(transcript, "business_id", "")
            if business_id:
                transcript_ids.add(str(business_id))

        if not context_parts:
            raise ValueError("Meeting transcript is empty.")

        event_context = []

        if self._organization_event_repository is not None:
            if callable(
                getattr(
                    self._organization_event_repository,
                    "find_by_correlation",
                    None,
                )
            ):
                organization_events = (
                    self._organization_event_repository.find_by_correlation(
                        meeting_id
                    )
                )
            elif callable(
                getattr(self._organization_event_repository, "all", None)
            ):
                # Compatibility for legacy repositories without correlation lookup.
                organization_events = self._organization_event_repository.all()
            else:
                organization_events = []

            seen_events = set()

            for event in organization_events:
                matched = False

                for observation in event.observations:
                    for evidence in observation.evidence:
                        evidence_text = str(evidence)
                        if any(
                            evidence_text == transcript_id
                            or evidence_text.startswith(transcript_id + ":")
                            for transcript_id in transcript_ids
                        ):
                            matched = True
                            break
                    if matched:
                        break

                if not matched:
                    corr = getattr(event, "correlation_id", None)
                    if corr is not None:
                        corr_str = (
                            corr.business_id
                            if hasattr(corr, "business_id") and corr.business_id
                            else str(getattr(corr, "graph_id", corr))
                        )
                        if corr_str == meeting_id:
                            matched = True

                if not matched:
                    continue

                event_type_str = (
                    event.event_type.value
                    if hasattr(event.event_type, "value")
                    else str(event.event_type)
                )

                key = (
                    event_type_str,
                    event.summary,
                )

                if key in seen_events:
                    continue

                seen_events.add(key)
                event_context.append(
                    f"{event_type_str}: {event.summary}"
                )

        context = "\n\n".join(context_parts)
        canonical_events = "\n".join(event_context) or "None recorded."

        try:
            if len(context) <= self.MAX_CONTEXT_CHARS:
                response = self._llm_client.generate(
                    self._build_analysis_prompt(
                        meeting_id=meeting_id,
                        context=context,
                        canonical_events=canonical_events,
                    )
                )
            else:
                chunks = self._chunk_context(context, self.MAX_CONTEXT_CHARS)
                section_results = []

                for index, chunk in enumerate(chunks, start=1):
                    section_response = self._llm_client.generate(
                        self._build_analysis_chunk_prompt(
                            meeting_id=meeting_id,
                            chunk=chunk,
                            index=index,
                            total=len(chunks),
                            canonical_events=canonical_events,
                        )
                    )
                    parsed = self._parse_structured_response(section_response)
                    section_results.append(
                        {
                            "summary": parsed.summary,
                            "topics": parsed.topics,
                            "decisions": parsed.decisions,
                            "action_items": parsed.action_items,
                            "risks": parsed.risks,
                            "open_questions": parsed.open_questions,
                            "confidence": parsed.confidence,
                        }
                    )

                response = self._llm_client.generate(
                    self._build_analysis_synthesis_prompt(
                        meeting_id=meeting_id,
                        context=json.dumps(section_results),
                        canonical_events=canonical_events,
                    )
                )

        except Exception:
            return MeetingIntelligenceResult(
                summary=(
                    "I found the meeting transcript, but I couldn't "
                    "generate reliable structured meeting intelligence."
                ),
                confidence=0.0,
                evidence=context_parts,
            )

        return self._parse_structured_response(
            response,
            evidence=context_parts,
        )

    @staticmethod
    def _parse_structured_response(
        response: str,
        evidence: list[str] | None = None,
    ) -> MeetingIntelligenceResult:
        try:
            data = json.loads(response)
        except (TypeError, json.JSONDecodeError):
            return MeetingIntelligenceResult(
                summary=(
                    "I found the meeting transcript, but I couldn't "
                    "generate reliable structured meeting intelligence."
                ),
                confidence=0.0,
                evidence=list(evidence or []),
            )

        if not isinstance(data, dict):
            return MeetingIntelligenceResult(
                summary=(
                    "I found the meeting transcript, but I couldn't "
                    "generate reliable structured meeting intelligence."
                ),
                confidence=0.0,
                evidence=list(evidence or []),
            )

        summary = str(data.get("summary", "") or "").strip()
        if not summary:
            summary = (
                "I found the meeting transcript, but I couldn't "
                "generate reliable structured meeting intelligence."
            )

        try:
            raw_confidence = data.get("confidence", 0.0)
            confidence = float(raw_confidence if raw_confidence is not None else 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))

        def _list(name: str) -> list[str]:
            value = data.get(name, [])
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        return MeetingIntelligenceResult(
            summary=summary,
            topics=_list("topics"),
            decisions=_list("decisions"),
            action_items=_list("action_items"),
            risks=_list("risks"),
            open_questions=_list("open_questions"),
            confidence=confidence,
            evidence=list(evidence or []),
        )

    @staticmethod
    def _build_analysis_prompt(
        *,
        meeting_id: str,
        context: str,
        canonical_events: str,
    ) -> str:
        return f"""
You are POLIS, an organizational meeting intelligence assistant.

Analyze the complete meeting transcript and produce structured meeting intelligence.

Meeting ID:
{meeting_id}

Canonical organizational events already extracted from this meeting:
{canonical_events}

Transcript:
{context}

Return ONLY valid JSON in this exact structure:
{{
  "summary": "concise meeting summary",
  "topics": ["main topic"],
  "decisions": ["explicitly made decision"],
  "action_items": ["explicitly assigned or agreed action"],
  "risks": ["explicitly discussed risk or unresolved issue"],
  "open_questions": ["important unresolved question"],
  "confidence": 0.0
}}

Rules:
- Use only information supported by the transcript or canonical events.
- Do not invent participants, owners, deadlines, decisions, or outcomes.
- Preserve explicit decisions, tasks, risks, and unresolved questions.
- Treat canonical organizational events as evidence, not as permission to infer new facts.
- Exclude greetings, filler, acknowledgements, and ASR noise.
- Deduplicate repeated points.
- Confidence must be between 0.0 and 1.0.
""".strip()

    @staticmethod
    def _build_analysis_chunk_prompt(
        *,
        meeting_id: str,
        chunk: str,
        index: int,
        total: int,
        canonical_events: str,
    ) -> str:
        return f"""
You are POLIS, an organizational meeting intelligence assistant.

Analyze section {index} of {total} of meeting {meeting_id}.

Canonical organizational events already extracted:
{canonical_events}

Transcript section:
{chunk}

Return ONLY valid JSON with summary, topics, decisions, action_items, risks, open_questions, confidence.
Use only explicit information. Ignore greetings, filler, acknowledgements, and ASR noise.
""".strip()

    @staticmethod
    def _build_analysis_synthesis_prompt(
        *,
        meeting_id: str,
        context: str,
        canonical_events: str,
    ) -> str:
        return f"""
You are POLIS, an organizational meeting intelligence assistant.

Create the final structured intelligence for meeting {meeting_id}.

Canonical organizational events:
{canonical_events}

Section analyses:
{context}

Return ONLY valid JSON with summary, topics, decisions, action_items, risks, open_questions, confidence.
Deduplicate repeated information and use only supported facts.
""".strip()

    def summarize(
        self,
        meeting_id: str,
    ) -> Answer:
        transcripts = (
            self._transcript_repository.find_by_meeting_id(
                meeting_id,
            )
        )

        if not transcripts:
            return Answer(
                text="I couldn't find a transcript for this meeting.",
                confidence=0.0,
                evidence=[],
            )

        context_parts = []

        for transcript in transcripts:
            if not transcript.transcript.strip():
                continue

            context_parts.append(
                transcript.transcript.strip()
            )

        if not context_parts:
            return Answer(
                text="The meeting transcript is empty.",
                confidence=0.0,
                evidence=[],
            )

        context = "\n\n".join(context_parts)

        try:
            if len(context) <= self.MAX_CONTEXT_CHARS:
                summary = self._llm_client.generate(
                    self._build_summary_prompt(
                        meeting_id=meeting_id,
                        context=context,
                    )
                )
            else:
                chunks = self._chunk_context(
                    context,
                    self.MAX_CONTEXT_CHARS,
                )

                chunk_summaries = []

                for index, chunk in enumerate(
                    chunks,
                    start=1,
                ):
                    chunk_summary = (
                        self._llm_client.generate(
                            self._build_chunk_prompt(
                                meeting_id=meeting_id,
                                chunk=chunk,
                                index=index,
                                total=len(chunks),
                            )
                        )
                    ).strip()

                    if not chunk_summary:
                        return Answer(
                            text=(
                                "I found the meeting transcript, "
                                "but I couldn't generate a reliable summary."
                            ),
                            confidence=0.0,
                            evidence=context_parts,
                        )

                    chunk_summaries.append(
                        chunk_summary
                    )

                synthesis_context = "\n\n".join(
                    f"Section {index}: {summary}"
                    for index, summary in enumerate(
                        chunk_summaries,
                        start=1,
                    )
                )

                summary = self._llm_client.generate(
                    self._build_synthesis_prompt(
                        meeting_id=meeting_id,
                        context=synthesis_context,
                    )
                )

        except Exception:
            summary = ""

        summary = summary.strip()

        if not summary:
            return Answer(
                text=(
                    "I found the meeting transcript, "
                    "but I couldn't generate a reliable summary."
                ),
                confidence=0.0,
                evidence=context_parts,
            )

        return Answer(
            text=summary,
            confidence=0.8,
            evidence=context_parts,
        )

    @staticmethod
    def _chunk_context(
        context: str,
        max_chars: int,
    ) -> list[str]:
        chunks = []
        current_parts = []
        current_length = 0

        for paragraph in context.split("\n\n"):
            paragraph = paragraph.strip()

            if not paragraph:
                continue

            if len(paragraph) > max_chars:
                if current_parts:
                    chunks.append(
                        "\n\n".join(current_parts)
                    )
                    current_parts = []
                    current_length = 0

                for start in range(
                    0,
                    len(paragraph),
                    max_chars,
                ):
                    chunks.append(
                        paragraph[start:start + max_chars]
                    )

                continue

            separator_length = 2 if current_parts else 0

            if (
                current_length
                + separator_length
                + len(paragraph)
                <= max_chars
            ):
                current_parts.append(paragraph)
                current_length += (
                    separator_length
                    + len(paragraph)
                )
            else:
                chunks.append(
                    "\n\n".join(current_parts)
                )
                current_parts = [paragraph]
                current_length = len(paragraph)

        if current_parts:
            chunks.append(
                "\n\n".join(current_parts)
            )

        return chunks

    @staticmethod
    def _build_summary_prompt(
        *,
        meeting_id: str,
        context: str,
    ) -> str:
        return f"""
You are POLIS, an organizational meeting intelligence assistant.

Summarize the following meeting transcript.

Meeting ID:
{meeting_id}

Transcript:
{context}

Instructions:
- Summarize only what is supported by the transcript.
- Do not invent participants, decisions, actions, dates, or outcomes.
- Identify the main topics discussed.
- Identify decisions that were explicitly made.
- Identify action items that were explicitly assigned or agreed.
- Identify important risks or unresolved issues explicitly discussed.
- Distinguish confirmed decisions from open discussion.
- Keep the summary concise and useful for an employee who did not attend.
- Do not mention internal systems, retrieval, embeddings, databases, or model behavior.
- Return ONLY the meeting summary.
""".strip()

    @staticmethod
    def _build_chunk_prompt(
        *,
        meeting_id: str,
        chunk: str,
        index: int,
        total: int,
    ) -> str:
        return f"""
You are POLIS, an organizational meeting intelligence assistant.

Analyze section {index} of {total} of a meeting transcript.

Meeting ID:
{meeting_id}

Transcript section:
{chunk}

Extract only information explicitly supported by this section.

Preserve:
- Main topics
- Explicit decisions
- Explicitly assigned or agreed action items
- Important risks or unresolved issues
- Important context needed to understand those items

Do not invent participants, dates, outcomes, or conclusions.
Return a concise section summary that can be combined with other sections.
Return ONLY the section summary.
""".strip()

    @staticmethod
    def _build_synthesis_prompt(
        *,
        meeting_id: str,
        context: str,
    ) -> str:
        return f"""
You are POLIS, an organizational meeting intelligence assistant.

Create the final meeting summary from the section summaries below.

Meeting ID:
{meeting_id}

Section summaries:
{context}

Instructions:
- Use only information supported by the section summaries.
- Do not invent participants, decisions, actions, dates, or outcomes.
- Identify the main topics discussed.
- Identify decisions that were explicitly made.
- Identify action items that were explicitly assigned or agreed.
- Identify important risks or unresolved issues.
- Distinguish confirmed decisions from open discussion.
- Remove duplication across sections.
- Keep the final summary concise and useful for an employee who did not attend.
- Do not mention sections, internal systems, retrieval, embeddings, databases, or model behavior.
- Return ONLY the final meeting summary.
""".strip()
