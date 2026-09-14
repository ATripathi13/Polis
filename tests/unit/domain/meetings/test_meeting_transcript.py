from datetime import datetime, timezone

import pytest

from domain.meetings import MeetingTranscript


def test_meeting_transcript_create():
    captured_at = datetime.now(timezone.utc)

    transcript = MeetingTranscript.create(
        meeting_id="meeting-001",
        transcript="We agreed to ship the dashboard on Friday.",
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice", "Bob"],
    )

    assert transcript.graph_id is not None
    assert transcript.meeting_id == "meeting-001"
    assert transcript.transcript == (
        "We agreed to ship the dashboard on Friday."
    )
    assert transcript.source == "Microsoft Teams"
    assert transcript.captured_at == captured_at
    assert transcript.participants == ["Alice", "Bob"]


def test_meeting_transcript_preserves_metadata():
    metadata = {
        "tenant_id": "tenant-001",
        "transcript_id": "transcript-001",
    }

    transcript = MeetingTranscript.create(
        meeting_id="meeting-002",
        transcript="Project discussion.",
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
        metadata=metadata,
    )

    assert transcript.metadata == metadata


def test_meeting_transcript_rejects_empty_meeting_id():
    with pytest.raises(ValueError, match="meeting_id must not be empty"):
        MeetingTranscript.create(
            meeting_id="",
            transcript="Project discussion.",
            source="Microsoft Teams",
            captured_at=datetime.now(timezone.utc),
        )


def test_meeting_transcript_rejects_empty_transcript():
    with pytest.raises(ValueError, match="transcript must not be empty"):
        MeetingTranscript.create(
            meeting_id="meeting-003",
            transcript="",
            source="Microsoft Teams",
            captured_at=datetime.now(timezone.utc),
        )


def test_meeting_transcript_rejects_empty_source():
    with pytest.raises(ValueError, match="source must not be empty"):
        MeetingTranscript.create(
            meeting_id="meeting-004",
            transcript="Project discussion.",
            source="",
            captured_at=datetime.now(timezone.utc),
        )