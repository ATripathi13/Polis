from datetime import datetime, timezone
from unittest.mock import Mock, patch

from infrastructure.meetings.microsoft_teams_subscription_provider import (
    MicrosoftTeamsSubscriptionProvider,
)


def test_create_subscription():
    token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsSubscriptionProvider(
        access_token_provider=token_provider,
    )

    expiration = datetime(
        2026,
        9,
        14,
        18,
        0,
        tzinfo=timezone.utc,
    )

    graph_response = {
        "id": "subscription-123",
        "resource": "communications/onlineMeetings/getAllTranscripts",
        "expirationDateTime": expiration.isoformat(),
        "clientState": "polis-teams-transcript",
    }

    with patch(
        "infrastructure.meetings.microsoft_teams_subscription_provider.requests.post"
    ) as post:

        post.return_value.json.return_value = graph_response
        post.return_value.raise_for_status.return_value = None

        result = provider.create_subscription(
            resource="communications/onlineMeetings/getAllTranscripts",
            notification_url="https://example.com/teams/webhook",
            expiration_datetime=expiration,
            client_state="polis-teams-transcript",
        )

    token_provider.assert_called_once()

    post.assert_called_once()

    call = post.call_args

    assert (
        call.args[0]
        == "https://graph.microsoft.com/v1.0/subscriptions"
    )

    assert call.kwargs["headers"] == {
        "Authorization": "Bearer test-access-token",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    assert call.kwargs["json"] == {
        "changeType": "created",
        "notificationUrl": "https://example.com/teams/webhook",
        "resource": "communications/onlineMeetings/getAllTranscripts",
        "expirationDateTime": expiration.isoformat(),
        "clientState": "polis-teams-transcript",
    }

    assert call.kwargs["timeout"] == 30.0

    assert result == graph_response

def test_renew_subscription():
    token_provider = Mock(
        return_value="test-access-token"
    )

    provider = MicrosoftTeamsSubscriptionProvider(
        access_token_provider=token_provider,
    )

    expiration = datetime(
        2026,
        9,
        14,
        19,
        0,
        tzinfo=timezone.utc,
    )

    graph_response = {
        "id": "subscription-123",
        "expirationDateTime": expiration.isoformat(),
    }

    with patch(
        "infrastructure.meetings.microsoft_teams_subscription_provider.requests.patch"
    ) as patch_request:

        patch_request.return_value.json.return_value = graph_response
        patch_request.return_value.raise_for_status.return_value = None

        result = provider.renew_subscription(
            subscription_id="subscription-123",
            expiration_datetime=expiration,
        )

    token_provider.assert_called_once()

    patch_request.assert_called_once()

    call = patch_request.call_args

    assert (
        call.args[0]
        == "https://graph.microsoft.com/v1.0/subscriptions/"
        "subscription-123"
    )

    assert call.kwargs["headers"] == {
        "Authorization": "Bearer test-access-token",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    assert call.kwargs["json"] == {
        "expirationDateTime": expiration.isoformat(),
    }

    assert call.kwargs["timeout"] == 30.0

    assert result == graph_response