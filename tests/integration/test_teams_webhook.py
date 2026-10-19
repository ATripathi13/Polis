import logging
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

    provider_timestamp = datetime(
        2026, 10, 19, 9, 30, 0, tzinfo=timezone.utc
    )

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
            captured_at=self.provider_timestamp,
            participants=[],
            metadata={
                "user_id": user_id,
                "online_meeting_id": online_meeting_id,
                "transcript_id": transcript_id,
                "meeting_started_at": "2026-10-19T09:00:00+00:00",
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
        **kwargs,
    ):
        self.calls.append(
            {
                "transcript": transcript,
                "meeting_id": meeting_id,
                "transcript_id": transcript_id,
                "kwargs": kwargs,
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

    provider_timestamp = provider.provider_timestamp

    assert teams_service.calls[0] == {
        "transcript": "Hello from the TNT4 Teams meeting.",
        "meeting_id": "meeting-456",
        "transcript_id": "transcript-789",
        "kwargs": {
            "meeting_start_time": "2026-10-19T09:00:00+00:00",
            "captured_at": provider_timestamp,
        },
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


def test_teams_webhook_logs_structured_progress(caplog):
    caplog.set_level(logging.INFO, logger="interfaces.api.routes.teams")
    transcript_service.ingested.clear()
    teams_service.calls.clear()

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

    response = client.post("/teams/webhook", json=payload)
    assert response.status_code == 200

    teams_records = [
        r for r in caplog.records if r.name == "interfaces.api.routes.teams"
    ]
    events = [getattr(r, "event", None) for r in teams_records]

    assert "teams_notification_parsed" in events
    assert "teams_transcript_retrieved" in events
    assert "teams_transcript_persisted" in events
    assert "teams_cognitive_processing_success" in events

    # Ensure no raw transcript text is logged
    for r in teams_records:
        assert "Hello from the TNT4 Teams meeting." not in r.getMessage()


def test_teams_webhook_logs_warning_when_transcript_not_found(caplog):
    caplog.set_level(logging.WARNING, logger="interfaces.api.routes.teams")

    class EmptyTranscriptProvider:
        def get_transcript_by_notification(
            self,
            *,
            user_id,
            online_meeting_id,
            transcript_id,
        ):
            return None

    app.dependency_overrides[
        get_meeting_transcript_provider
    ] = lambda: EmptyTranscriptProvider()
    try:
        payload = {
            "value": [
                {
                    "clientState": "polis-teams-transcript",
                    "resource": (
                        "users('user-999')/"
                        "onlineMeetings('meeting-999')/"
                        "transcripts('transcript-999')"
                    ),
                    "resourceData": {
                        "id": "transcript-999",
                    },
                }
            ]
        }
        response = client.post("/teams/webhook", json=payload)
        assert response.status_code == 200

        warning_records = [
            r for r in caplog.records
            if r.name == "interfaces.api.routes.teams"
            and r.levelname == "WARNING"
        ]
        assert any(
            getattr(r, "event", None) == "teams_transcript_not_found"
            for r in warning_records
        )
    finally:
        app.dependency_overrides[
            get_meeting_transcript_provider
        ] = lambda: provider


def test_teams_webhook_logs_warning_on_unparseable_resource(caplog):
    caplog.set_level(logging.WARNING, logger="interfaces.api.routes.teams")

    payload = {
        "value": [
            {
                "clientState": "polis-teams-transcript",
                "resource": "invalid/resource/format",
                "resourceData": {
                    "id": "transcript-789",
                },
            }
        ]
    }
    response = client.post("/teams/webhook", json=payload)
    assert response.status_code == 200

    warning_records = [
        r for r in caplog.records
        if r.name == "interfaces.api.routes.teams"
        and r.levelname == "WARNING"
    ]
    assert any(
        getattr(r, "event", None) == "teams_resource_parse_error"
        for r in warning_records
    )
