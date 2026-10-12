"""
Application service for meeting transcript ingestion.
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from application.meetings.meeting_transcript_input import (
    MeetingTranscriptInput,
)
from domain.common.identifier import Identifier
from domain.meetings import Meeting, MeetingTranscript
from domain.meetings.repositories import (
    MeetingRepository,
    MeetingTranscriptRepository,
)


class MeetingTranscriptService:
    """
    Coordinates creation and persistence of meeting transcripts.

    This service stores the raw transcript only.
    Knowledge extraction is intentionally handled separately.
    """

    def __init__(
        self,
        repository: MeetingTranscriptRepository,
        meeting_repository: MeetingRepository | None = None,
    ) -> None:
        self.repository = repository
        self.meeting_repository = meeting_repository

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
        self._upsert_meeting(data)

        return meeting_transcript

    def _upsert_meeting(
        self,
        data: MeetingTranscriptInput,
    ) -> None:
        """
        Persist a canonical meeting when authoritative metadata exists.
        """

        if self.meeting_repository is None:
            return

        title = str(
            data.metadata.get("meeting_title", "")
        ).strip()
        started_raw = data.metadata.get(
            "meeting_started_at"
        )

        if not title or not started_raw:
            return

        try:
            started_at = datetime.fromisoformat(
                str(started_raw).replace(
                    "Z",
                    "+00:00",
                )
            )
        except (TypeError, ValueError):
            return

        ended_at = None
        ended_raw = data.metadata.get(
            "meeting_ended_at"
        )

        if ended_raw:
            try:
                ended_at = datetime.fromisoformat(
                    str(ended_raw).replace(
                        "Z",
                        "+00:00",
                    )
                )
            except (TypeError, ValueError):
                ended_at = None

        existing = self.meeting_repository.find_by_external_id(
            data.meeting_id
        )

        if existing is None:
            meeting = Meeting.create(
                external_id=data.meeting_id,
                title=title,
                source=data.source,
                started_at=started_at,
                ended_at=ended_at,
                metadata=data.metadata,
                business_id=data.meeting_id,
            )
        else:
            meeting = Meeting(
                identifier=Identifier(
                    graph_id=existing.graph_id,
                ),
                external_id=data.meeting_id,
                title=title,
                source=data.source,
                started_at=started_at,
                ended_at=ended_at,
                metadata=data.metadata,
            )

        self.meeting_repository.save(meeting)

    def ingest_from_provider(
        self,
        provider,
        meeting_id: str,
    ) -> MeetingTranscript | None:
        data = provider.get_transcript(meeting_id)

        if data is None:
            return None

        return self.ingest(data)