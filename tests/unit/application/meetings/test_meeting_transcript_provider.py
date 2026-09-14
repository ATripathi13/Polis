from datetime import datetime, timezone

from application.meetings.meeting_transcript_input import (
    MeetingTranscriptInput,
)
from application.meetings.meeting_transcript_provider import (
    MeetingTranscriptProvider,
)


class FakeMeetingTranscriptProvider(MeetingTranscriptProvider):
    def __init__(self, transcript=None):
        self.transcript = transcript
        self.requested_meeting_id = None

    def get_transcript(
        self,
        meeting_id: str,
    ) -> MeetingTranscriptInput | None:
        self.requested_meeting_id = meeting_id
        return self.transcript


def test_provider_returns_transcript_input():
    expected = MeetingTranscriptInput(
        meeting_id="meeting-001",
        transcript="Test transcript.",
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
    )

    provider = FakeMeetingTranscriptProvider(expected)

    result = provider.get_transcript("meeting-001")

    assert result is expected
    assert provider.requested_meeting_id == "meeting-001"


def test_provider_can_return_no_transcript():
    provider = FakeMeetingTranscriptProvider()

    result = provider.get_transcript("meeting-002")

    assert result is None
    assert provider.requested_meeting_id == "meeting-002"