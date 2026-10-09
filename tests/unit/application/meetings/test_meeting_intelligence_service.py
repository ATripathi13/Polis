from datetime import datetime, timezone

from application.meetings.meeting_intelligence_service import (
    MeetingIntelligenceService,
)
from domain.meetings import MeetingTranscript
from domain.common.identifier import Identifier


class FakeTranscriptRepository:
    def __init__(self, transcripts):
        self.transcripts = transcripts

    def find_by_meeting_id(self, meeting_id):
        return [
            transcript
            for transcript in self.transcripts
            if transcript.meeting_id == meeting_id
        ]


class FakeLLMClient:
    def __init__(self, response):
        self.response = response
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return self.response


def make_transcript(meeting_id, transcript):
    return MeetingTranscript(
        identifier=Identifier(),
        meeting_id=meeting_id,
        transcript=transcript,
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
    )


def test_summarize_uses_meeting_transcript():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-001",
                "Alice: We agreed to launch Friday. Bob: I will publish the release notes.",
            )
        ]
    )
    llm = FakeLLMClient(
        "The team agreed to launch Friday. Bob will publish the release notes."
    )

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
    )

    result = service.summarize("meeting-001")

    assert (
        result.text
        == "The team agreed to launch Friday. Bob will publish the release notes."
    )
    assert result.confidence == 0.8
    assert len(result.evidence) == 1
    assert "Alice: We agreed to launch Friday." in result.evidence[0]
    assert "meeting-001" in llm.prompt


def test_summarize_returns_not_found_when_transcript_missing():
    repository = FakeTranscriptRepository([])
    llm = FakeLLMClient("unused")

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
    )

    result = service.summarize("missing-meeting")

    assert result.text == "I couldn't find a transcript for this meeting."
    assert result.confidence == 0.0
    assert result.evidence == []
    assert llm.prompt is None


def test_summarize_handles_llm_failure():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-002",
                "The project is blocked by the missing approval.",
            )
        ]
    )

    class FailingLLM:
        def generate(self, prompt):
            raise RuntimeError("llm failure")

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=FailingLLM(),
    )

    result = service.summarize("meeting-002")

    assert (
        result.text
        == "I found the meeting transcript, but I couldn't generate a reliable summary."
    )
    assert result.confidence == 0.0
    assert len(result.evidence) == 1

def test_summarize_chunks_long_meeting_transcript():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-long",
                "\n\n".join(
                    "A" * 10000
                    for _ in range(5)
                ),
            )
        ]
    )

    class RecordingLLM:
        def __init__(self):
            self.calls = []

        def generate(self, prompt):
            self.calls.append(prompt)
            return "Section summary."

    llm = RecordingLLM()

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
    )

    result = service.summarize("meeting-long")

    assert result.text == "Section summary."
    assert len(llm.calls) == 4
    assert all("meeting-long" in prompt for prompt in llm.calls)
    assert len(llm.calls[0]) < 25000
    assert len(llm.calls[1]) < 25000
    assert len(llm.calls[2]) < 25000
