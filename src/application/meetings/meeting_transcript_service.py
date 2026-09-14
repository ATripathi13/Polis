"""
Application service for meeting transcript ingestion.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from application.meetings.meeting_transcript_input import (
    MeetingTranscriptInput,
)
from domain.common.identifier import Identifier
from domain.meetings import MeetingTranscript
from domain.meetings.repositories import MeetingTranscriptRepository


class MeetingTranscriptService:
    """
    Coordinates creation and persistence of meeting transcripts.

    This service stores the raw transcript only.
    Knowledge extraction is intentionally handled separately.
    """

    def __init__(
        self,
        repository: MeetingTranscriptRepository,
    ) -> None:
        self.repository = repository

    def ingest(
        self,
        data: MeetingTranscriptInput,
    ) -> MeetingTranscript:

        transcript_id = data.metadata.get("transcript_id")

        if transcript_id:
            stable_graph_id = uuid5(
                NAMESPACE_URL,
                f"microsoft-teams:transcript:{transcript_id}",
            )

            meeting_transcript = MeetingTranscript(
                identifier=Identifier(
                    graph_id=stable_graph_id,
                    business_id=transcript_id,
                ),
                meeting_id=data.meeting_id,
                transcript=data.transcript,
                source=data.source,
                captured_at=data.captured_at,
                participants=data.participants,
                metadata=data.metadata,
            )

        else:
            meeting_transcript = MeetingTranscript.create(
                meeting_id=data.meeting_id,
                transcript=data.transcript,
                source=data.source,
                captured_at=data.captured_at,
                participants=data.participants,
                metadata=data.metadata,
            )

        self.repository.save(meeting_transcript)

        return meeting_transcript

    def ingest_from_provider(
        self,
        provider,
        meeting_id: str,
    ) -> MeetingTranscript | None:
        data = provider.get_transcript(meeting_id)

        if data is None:
            return None

        return self.ingest(data)