from datetime import timedelta

from connectors.microsoft_teams.models import (
    TeamsTranscriptSegment,
)
from connectors.microsoft_teams.services import (
    TeamsService,
)


class FakeNormalizer:

    def normalize(
        self,
        *,
        segment,
        meeting_id,
        transcript_id,
    ):
        return {
            "segment": segment,
            "meeting_id": meeting_id,
            "transcript_id": transcript_id,
        }


class FakeCommunicationService:

    def __init__(self):
        self.commands = []

    def process(self, command):
        self.commands.append(command)
        return command.event


class FakeCognitiveEngine:

    def __init__(self):
        self.learned = []

    def learn(self, communication):
        self.learned.append(communication)


def test_teams_service_processes_every_segment(monkeypatch):

    segments = [
        TeamsTranscriptSegment(
            speaker="Speaker A",
            text="Hello.",
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
        ),
        TeamsTranscriptSegment(
            speaker="Speaker B",
            text="We should continue.",
            start=timedelta(seconds=3),
            end=timedelta(seconds=5),
        ),
    ]

    monkeypatch.setattr(
        "connectors.microsoft_teams.services.teams_service.parse_teams_vtt",
        lambda transcript: segments,
    )

    normalizer = FakeNormalizer()
    communication_service = FakeCommunicationService()
    cognitive_engine = FakeCognitiveEngine()

    service = TeamsService(
        normalizer=normalizer,
        communication_service=communication_service,
        cognitive_engine=cognitive_engine,
    )

    result = service.ingest_transcript(
        transcript="unused",
        meeting_id="meeting-123",
        transcript_id="transcript-456",
    )

    assert len(result) == 2
    assert len(communication_service.commands) == 2
    assert len(cognitive_engine.learned) == 2

    assert (
        cognitive_engine.learned[0]["segment"].speaker
        == "Speaker A"
    )

    assert (
        cognitive_engine.learned[1]["segment"].speaker
        == "Speaker B"
    )


def test_teams_service_returns_empty_for_empty_transcript():

    normalizer = FakeNormalizer()
    communication_service = FakeCommunicationService()
    cognitive_engine = FakeCognitiveEngine()

    service = TeamsService(
        normalizer=normalizer,
        communication_service=communication_service,
        cognitive_engine=cognitive_engine,
    )

    result = service.ingest_transcript(
        transcript="",
        meeting_id="meeting-123",
        transcript_id="transcript-456",
    )

    assert result == []
    assert communication_service.commands == []
    assert cognitive_engine.learned == []
