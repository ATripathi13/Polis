from unittest.mock import Mock, patch

from infrastructure.meetings.microsoft_teams_recording_provider import (
    MicrosoftTeamsRecordingProvider,
)


def test_get_recording_by_notification_returns_recording_input():
    response = Mock()
    response.status_code = 200
    response.content = b"fake-mp4-content"
    response.headers = {
        "Content-Type": "video/mp4",
    }

    access_token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsRecordingProvider(
        access_token_provider
    )

    with patch(
        "infrastructure.meetings.microsoft_teams_recording_provider.requests.get",
        return_value=response,
    ) as mock_get:

        result = provider.get_recording_by_notification(
            user_id="user-001",
            online_meeting_id="meeting-001",
            recording_id="recording-001",
        )

    assert result is not None
    assert result.meeting_id == "meeting-001"
    assert result.content == b"fake-mp4-content"
    assert result.source == "Microsoft Teams"
    assert result.content_type == "video/mp4"

    assert result.metadata == {
        "provider": "microsoft_graph",
        "user_id": "user-001",
        "online_meeting_id": "meeting-001",
        "recording_id": "recording-001",
    }

    assert mock_get.call_count == 1


def test_get_recording_by_notification_returns_none_for_missing_recording():
    response = Mock()
    response.status_code = 404

    access_token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsRecordingProvider(
        access_token_provider
    )

    with patch(
        "infrastructure.meetings.microsoft_teams_recording_provider.requests.get",
        return_value=response,
    ):

        result = provider.get_recording_by_notification(
            user_id="user-001",
            online_meeting_id="meeting-001",
            recording_id="recording-002",
        )

    assert result is None


def test_get_recording_by_notification_returns_none_for_empty_content():
    response = Mock()
    response.status_code = 200
    response.content = b""
    response.headers = {
        "Content-Type": "video/mp4",
    }

    access_token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsRecordingProvider(
        access_token_provider
    )

    with patch(
        "infrastructure.meetings.microsoft_teams_recording_provider.requests.get",
        return_value=response,
    ):

        result = provider.get_recording_by_notification(
            user_id="user-001",
            online_meeting_id="meeting-001",
            recording_id="recording-003",
        )

    assert result is None
