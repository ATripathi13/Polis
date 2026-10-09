from __future__ import annotations

from domain.meetings.repositories.meeting_transcript_repository import (
    MeetingTranscriptRepository,
)
from domain.reasoning.value_objects import Answer
from infrastructure.llm import OpenRouterClient


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
    ) -> None:
        self._transcript_repository = transcript_repository
        self._llm_client = llm_client

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
