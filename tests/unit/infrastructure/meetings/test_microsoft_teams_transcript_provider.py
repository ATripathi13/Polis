from datetime import datetime, timezone
from unittest.mock import Mock, patch

from infrastructure.meetings.microsoft_teams_transcript_provider import (
    MicrosoftTeamsTranscriptProvider,
)


def test_get_transcript_returns_transcript_input():
    metadata_response = Mock()
    metadata_response.status_code = 200
    metadata_response.json.return_value = {
        "value": [
            {
                "id": "transcript-001",
                "createdDateTime": "2026-09-10T10:00:00Z",
            }
        ]
    }

    content_response = Mock()
    content_response.status_code = 200
    content_response.text = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:04.000\n"
        "<v Alice>We agreed to ship the dashboard on Friday."
    )

    access_token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsTranscriptProvider(
        access_token_provider
    )

    with patch(
        "infrastructure.meetings.microsoft_teams_transcript_provider.requests.get",
        side_effect=[
            metadata_response,
            content_response,
        ],
    ) as mock_get:

        result = provider.get_transcript("meeting-001")

    assert result is not None
    assert result.meeting_id == "meeting-001"
    assert result.transcript.startswith("WEBVTT")
    assert result.source == "Microsoft Teams"
    assert result.captured_at == datetime(
        2026,
        9,
        10,
        10,
        0,
        tzinfo=timezone.utc,
    )

    assert result.metadata == {
        "provider": "microsoft_graph",
        "transcript_id": "transcript-001",
    }

    assert mock_get.call_count == 2


def test_get_transcript_returns_none_when_no_transcript_exists():
    metadata_response = Mock()
    metadata_response.status_code = 200
    metadata_response.json.return_value = {
        "value": []
    }

    access_token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsTranscriptProvider(
        access_token_provider
    )

    with patch(
        "infrastructure.meetings.microsoft_teams_transcript_provider.requests.get",
        return_value=metadata_response,
    ):

        result = provider.get_transcript("meeting-002")

    assert result is None


def test_get_transcript_returns_none_for_missing_meeting():
    response = Mock()
    response.status_code = 404

    access_token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsTranscriptProvider(
        access_token_provider
    )

    with patch(
        "infrastructure.meetings.microsoft_teams_transcript_provider.requests.get",
        return_value=response,
    ):

        result = provider.get_transcript("meeting-003")

    assert result is None