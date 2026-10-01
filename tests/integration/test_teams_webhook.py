from datetime import datetime, timezone
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import (
    get_meeting_transcript_provider,
    get_meeting_transcript_service,
    get_teams_service,
)
from application.meetings import MeetingTranscriptInput


class FakeTranscriptProvider:

    def get_transcript_by_notification(
        self,
        *,
        user_id,
        online_meeting_id,
        transcript_id,
    ):
        return MeetingTranscriptInput(
            meeting_id=online_meeting_id,
            transcript="Hello from the TNT4 Teams meeting.",
            source="Microsoft Teams",
            captured_at=datetime.now(timezone.utc),
            participants=[],
            metadata={
                "user_id": user_id,
                "online_meeting_id": online_meeting_id,
                "transcript_id": transcript_id,
            },
        )


class FakeTranscriptService:

    def __init__(self):
        self.ingested = []

    def ingest(self, transcript):
        self.ingested.append(transcript)


class FakeTeamsService:

    def __init__(self):
        self.calls = []

    def ingest_transcript(
        self,
        *,
        transcript,
        meeting_id,
        transcript_id,
    ):
        self.calls.append(
            {
                "transcript": transcript,
                "meeting_id": meeting_id,
                "transcript_id": transcript_id,
            }
        )
        return ["communication-event-1"]


provider = FakeTranscriptProvider()
transcript_service = FakeTranscriptService()
teams_service = FakeTeamsService()

app.dependency_overrides[
    get_meeting_transcript_provider
] = lambda: provider

app.dependency_overrides[
    get_meeting_transcript_service
] = lambda: transcript_service

app.dependency_overrides[
    get_teams_service
] = lambda: teams_service


client = TestClient(app)


def test_teams_webhook_processes_transcript_notification():

    payload = {
        "value": [
            {
                "clientState": "polis-teams-transcript",
                "resource": (
                    "users('user-123')/"
                    "onlineMeetings('meeting-456')/"
                    "transcripts('transcript-789')"
                ),
                "resourceData": {
                    "id": "transcript-789",
                },
            }
        ]
    }

    response = client.post(
        "/teams/webhook",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    assert len(transcript_service.ingested) == 1

    assert (
        transcript_service.ingested[0].meeting_id
        == "meeting-456"
    )

    assert len(teams_service.calls) == 1

    assert teams_service.calls[0] == {
        "transcript": "Hello from the TNT4 Teams meeting.",
        "meeting_id": "meeting-456",
        "transcript_id": "transcript-789",
    }
def test_teams_webhook_returns_validation_token():

    validation_token = "teams-validation-token-123"

    response = client.post(
        "/teams/webhook",
        params={
            "validationToken": validation_token,
        },
    )

    assert response.status_code == 200
    assert response.text == validation_token
    assert response.headers["content-type"].startswith(
        "text/plain"
    )
