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

        prompt = f"""
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

        try:
            summary = self._llm_client.generate(prompt)
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
