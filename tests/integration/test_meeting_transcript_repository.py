from datetime import datetime, timedelta, timezone
from uuid import uuid4

from domain.meetings import MeetingTranscript
from domain.common.identifier import Identifier
from infrastructure.database.connection import SessionLocal
from infrastructure.database.meeting_transcript_repository import (
    PostgreSQLMeetingTranscriptRepository,
)
from infrastructure.database.models import MeetingTranscriptModel


def test_meeting_transcript_repository_save_and_find():
    repository = PostgreSQLMeetingTranscriptRepository()

    transcript = MeetingTranscript.create(
        meeting_id = str(uuid4()),
        transcript="We agreed to ship the dashboard on Friday.",
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
        participants=["Alice", "Bob"],
        metadata={"test": True},
    )

    repository.save(transcript)

    try:
        found = repository.find(
            str(transcript.graph_id)
        )

        assert found is not None
        assert found.graph_id == transcript.graph_id
        assert found.meeting_id == transcript.meeting_id
        assert found.transcript == transcript.transcript
        assert found.source == transcript.source
        assert found.captured_at == transcript.captured_at
        assert found.participants == transcript.participants
        assert found.metadata == transcript.metadata

    finally:
        with SessionLocal() as session:
            record = session.get(
                MeetingTranscriptModel,
                str(transcript.graph_id),
            )

            if record is not None:
                session.delete(record)
                session.commit()


def test_meeting_transcript_repository_find_by_meeting_id():
    repository = PostgreSQLMeetingTranscriptRepository()

    meeting_id = str(uuid4())
    captured_at = datetime.now(timezone.utc)

    first = MeetingTranscript.create(
        meeting_id=meeting_id,
        transcript="First part of the meeting.",
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice", "Bob"],
    )

    second = MeetingTranscript.create(
        meeting_id=meeting_id,
        transcript="Second part of the meeting.",
        source="Microsoft Teams",
        captured_at=captured_at + timedelta(minutes=10),
        participants=["Alice", "Bob"],
    )

    repository.save(first)
    repository.save(second)

    try:
        found = repository.find_by_meeting_id(meeting_id)

        assert len(found) == 2
        assert found[0].graph_id == first.graph_id
        assert found[0].transcript == first.transcript
        assert found[1].graph_id == second.graph_id
        assert found[1].transcript == second.transcript

    finally:
        with SessionLocal() as session:
            records = (
                session.query(MeetingTranscriptModel)
                .filter(
                    MeetingTranscriptModel.meeting_id == meeting_id
                )
                .all()
            )

            for record in records:
                session.delete(record)

            session.commit()

def test_meeting_transcript_repository_save_is_idempotent_for_same_id():
    repository = PostgreSQLMeetingTranscriptRepository()

    transcript_id = uuid4()
    meeting_id = str(uuid4())

    first = MeetingTranscript(
        identifier=Identifier(
            graph_id=transcript_id,
            business_id="graph-transcript-001",
        ),
        meeting_id=meeting_id,
        transcript="Original transcript.",
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
        participants=["Alice"],
        metadata={
            "transcript_id": "graph-transcript-001",
        },
    )

    second = MeetingTranscript(
        identifier=Identifier(
            graph_id=transcript_id,
            business_id="graph-transcript-001",
        ),
        meeting_id=meeting_id,
        transcript="Updated transcript.",
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
        participants=["Alice", "Bob"],
        metadata={
            "transcript_id": "graph-transcript-001",
        },
    )

    repository.save(first)
    repository.save(second)

    try:
        found = repository.find(str(transcript_id))

        assert found is not None
        assert found.graph_id == transcript_id
        assert found.transcript == "Updated transcript."
        assert found.participants == ["Alice", "Bob"]
        assert found.metadata["transcript_id"] == "graph-transcript-001"

        with SessionLocal() as session:
            records = (
                session.query(MeetingTranscriptModel)
                .filter(
                    MeetingTranscriptModel.id == str(transcript_id)
                )
                .all()
            )

            assert len(records) == 1

    finally:
        with SessionLocal() as session:
            record = session.get(
                MeetingTranscriptModel,
                str(transcript_id),
            )

            if record is not None:
                session.delete(record)
                session.commit()            