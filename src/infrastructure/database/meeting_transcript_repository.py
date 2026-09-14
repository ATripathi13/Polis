"""
PostgreSQL repository for meeting transcripts.
"""

from __future__ import annotations

from uuid import UUID

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import MeetingTranscriptModel

from domain.common.identifier import Identifier
from domain.meetings import MeetingTranscript
from domain.meetings.repositories.meeting_transcript_repository import (
    MeetingTranscriptRepository,
)


class PostgreSQLMeetingTranscriptRepository(
    MeetingTranscriptRepository
):
    """
    PostgreSQL implementation of MeetingTranscriptRepository.
    """

    def save(
        self,
        transcript: MeetingTranscript,
    ) -> None:

        with SessionLocal() as session:

            record = session.get(
                MeetingTranscriptModel,
                str(transcript.graph_id),
            )

            if record is None:

                record = MeetingTranscriptModel(
                    id=str(transcript.graph_id),
                    meeting_id=transcript.meeting_id,
                    transcript=transcript.transcript,
                    source=transcript.source,
                    captured_at=transcript.captured_at,
                    participants=transcript.participants,
                    metadata_=transcript.metadata,
                )

                session.add(record)

            else:

                record.meeting_id = transcript.meeting_id
                record.transcript = transcript.transcript
                record.source = transcript.source
                record.captured_at = transcript.captured_at
                record.participants = transcript.participants
                record.metadata_ = transcript.metadata

            session.commit()

    def find(
        self,
        identifier: str,
    ) -> MeetingTranscript | None:

        with SessionLocal() as session:

            record = session.get(
                MeetingTranscriptModel,
                identifier,
            )

            if record is None:
                return None

            return self._to_domain(record)

    def find_by_meeting_id(
        self,
        meeting_id: str,
    ) -> list[MeetingTranscript]:

        with SessionLocal() as session:

            records = (
                session.query(MeetingTranscriptModel)
                .filter(
                    MeetingTranscriptModel.meeting_id == meeting_id
                )
                .order_by(
                    MeetingTranscriptModel.captured_at.asc()
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

    @staticmethod
    def _to_domain(
        record: MeetingTranscriptModel,
    ) -> MeetingTranscript:

        return MeetingTranscript(
            identifier=Identifier(
                graph_id=UUID(record.id),
            ),
            meeting_id=record.meeting_id,
            transcript=record.transcript,
            source=record.source,
            captured_at=record.captured_at,
            participants=list(record.participants or []),
            metadata=dict(record.metadata_ or {}),
        )