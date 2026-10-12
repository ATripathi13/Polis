from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5
from application.meetings import MeetingTranscriptService
from application.meetings.meeting_transcript_input import (
    MeetingTranscriptInput,
)
from domain.meetings import MeetingTranscript


class FakeMeetingTranscriptRepository:
    def __init__(self):
        self.saved = []

    def save(self, transcript: MeetingTranscript) -> None:
        self.saved.append(transcript)


class FakeMeetingRepository:
    def __init__(self):
        self.saved = []
        self.meetings = {}

    def save(self, meeting):
        self.saved.append(meeting)
        self.meetings[meeting.external_id] = meeting

    def find_by_external_id(self, external_id):
        return self.meetings.get(external_id)


def test_ingest_creates_and_persists_transcript():
    repository = FakeMeetingTranscriptRepository()
    service = MeetingTranscriptService(repository)

    captured_at = datetime.now(timezone.utc)

    data = MeetingTranscriptInput(
        meeting_id="meeting-001",
        transcript="We agreed to ship the dashboard on Friday.",
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice", "Bob"],
        metadata={"tenant_id": "tenant-001"},
    )

    result = service.ingest(data)

    assert isinstance(result, MeetingTranscript)

    assert result.meeting_id == "meeting-001"
    assert result.transcript == (
        "We agreed to ship the dashboard on Friday."
    )
    assert result.source == "Microsoft Teams"
    assert result.captured_at == captured_at
    assert result.participants == ["Alice", "Bob"]
    assert result.metadata == {
        "tenant_id": "tenant-001",
    }

    assert len(repository.saved) == 1
    assert repository.saved[0] is result

def test_ingest_from_provider_persists_transcript():
    repository = FakeMeetingTranscriptRepository()

    captured_at = datetime.now(timezone.utc)

    data = MeetingTranscriptInput(
        meeting_id="meeting-002",
        transcript="The launch is scheduled for Friday.",
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice", "Bob"],
    )

    class FakeProvider:
        def get_transcript(self, meeting_id):
            assert meeting_id == "meeting-002"
            return data

    service = MeetingTranscriptService(repository)

    result = service.ingest_from_provider(
        FakeProvider(),
        "meeting-002",
    )

    assert result is not None
    assert result.meeting_id == "meeting-002"
    assert result.transcript == (
        "The launch is scheduled for Friday."
    )

    assert len(repository.saved) == 1
    assert repository.saved[0] is result

def test_ingest_uses_transcript_id_as_stable_identifier():
    repository = FakeMeetingTranscriptRepository()
    service = MeetingTranscriptService(repository)

    captured_at = datetime.now(timezone.utc)

    data = MeetingTranscriptInput(
        meeting_id="meeting-003",
        transcript="This transcript has a stable Graph identity.",
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice", "Bob"],
        metadata={
            "transcript_id": "graph-transcript-001",
        },
    )

    result = service.ingest(data)

    assert result.graph_id is not None
    expected_graph_id = uuid5(
    NAMESPACE_URL,
        "microsoft-teams:transcript:graph-transcript-001",
    )

    assert result.graph_id == expected_graph_id
    assert result.metadata["transcript_id"] == "graph-transcript-001"

    assert len(repository.saved) == 1
    assert repository.saved[0] is result

def test_ingest_creates_canonical_meeting_when_metadata_exists():
    repository = FakeMeetingTranscriptRepository()
    meeting_repository = FakeMeetingRepository()

    service = MeetingTranscriptService(
        repository,
        meeting_repository=meeting_repository,
    )

    captured_at = datetime.now(timezone.utc)

    data = MeetingTranscriptInput(
        meeting_id="meeting-004",
        transcript="The team agreed to ship Friday.",
        source="Microsoft Teams",
        captured_at=captured_at,
        metadata={
            "meeting_title": "Weekly Planning",
            "meeting_started_at": "2026-10-12T10:00:00Z",
            "meeting_ended_at": "2026-10-12T10:30:00Z",
        },
    )

    result = service.ingest(data)

    assert isinstance(result, MeetingTranscript)
    assert len(meeting_repository.saved) == 1

    meeting = meeting_repository.saved[0]

    assert meeting.external_id == "meeting-004"
    assert meeting.title == "Weekly Planning"
    assert meeting.source == "Microsoft Teams"
    assert meeting.started_at == datetime(
        2026, 10, 12, 10, 0, tzinfo=timezone.utc
    )
    assert meeting.ended_at == datetime(
        2026, 10, 12, 10, 30, tzinfo=timezone.utc
    )
