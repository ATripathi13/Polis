from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from application.meetings.teams_subscription_service import (
    TeamsSubscriptionService,
)
from domain.meetings import TeamsSubscription


def test_existing_active_subscription_is_reused():
    repository = Mock()
    provider = Mock()

    existing = TeamsSubscription.create(
        subscription_id="existing-subscription",
        resource="communications/onlineMeetings/getAllTranscripts",
        expiration_datetime=datetime(
            2026,
            9,
            14,
            18,
            0,
            tzinfo=timezone.utc,
        ),
        client_state="polis-teams-transcript",
        created_at=datetime(
            2026,
            9,
            14,
            17,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            9,
            14,
            17,
            0,
            tzinfo=timezone.utc,
        ),
    )

    repository.find_active.return_value = existing

    service = TeamsSubscriptionService(
        repository=repository,
        provider=provider,
        notification_url="https://example.com/teams/webhook",
    )

    result = service.ensure_subscription()

    assert result is existing

    provider.create_subscription.assert_not_called()
    repository.save.assert_not_called()


def test_missing_subscription_creates_and_saves_subscription():
    repository = Mock()
    provider = Mock()

    repository.find_active.return_value = None

    expiration = datetime(
        2026,
        9,
        14,
        18,
        0,
        tzinfo=timezone.utc,
    )

    provider.create_subscription.return_value = {
        "id": "new-subscription",
        "resource": (
            "communications/onlineMeetings/"
            "getAllTranscripts"
        ),
        "expirationDateTime": expiration.isoformat(),
        "clientState": "polis-teams-transcript",
    }

    service = TeamsSubscriptionService(
        repository=repository,
        provider=provider,
        notification_url="https://example.com/teams/webhook",
    )

    result = service.ensure_subscription()

    provider.create_subscription.assert_called_once()

    call = provider.create_subscription.call_args

    assert call.kwargs["resource"] == (
        "communications/onlineMeetings/getAllTranscripts"
    )

    assert call.kwargs["notification_url"] == (
        "https://example.com/teams/webhook"
    )

    assert call.kwargs["client_state"] == (
        "polis-teams-transcript"
    )

    assert result.subscription_id == "new-subscription"
    assert result.resource == (
        "communications/onlineMeetings/getAllTranscripts"
    )
    assert result.client_state == "polis-teams-transcript"

    repository.save.assert_called_once_with(result)

def test_subscription_near_expiry_is_renewed_and_saved():
    repository = Mock()
    provider = Mock()

    now = datetime(
        2026,
        9,
        14,
        17,
        50,
        tzinfo=timezone.utc,
    )

    existing_expiration = datetime(
        2026,
        9,
        14,
        18,
        0,
        tzinfo=timezone.utc,
    )

    renewed_expiration = datetime(
        2026,
        9,
        14,
        19,
        0,
        tzinfo=timezone.utc,
    )

    existing = TeamsSubscription.create(
        subscription_id="existing-subscription",
        resource="communications/onlineMeetings/getAllTranscripts",
        expiration_datetime=existing_expiration,
        client_state="polis-teams-transcript",
        created_at=now - timedelta(minutes=30),
        updated_at=now - timedelta(minutes=30),
    )

    repository.find_active.return_value = existing

    provider.renew_subscription.return_value = {
        "id": "existing-subscription",
        "resource": "communications/onlineMeetings/getAllTranscripts",
        "expirationDateTime": renewed_expiration.isoformat(),
        "clientState": "polis-teams-transcript",
    }

    service = TeamsSubscriptionService(
        repository=repository,
        provider=provider,
        notification_url="https://example.com/teams/webhook",
        now_provider=lambda: now,
    )

    result = service.ensure_subscription()

    provider.renew_subscription.assert_called_once_with(
        subscription_id="existing-subscription",
        expiration_datetime=datetime(
            2026,
            9,
            14,
            18,
            50,
            tzinfo=timezone.utc,
        ),
    )

    repository.save.assert_called_once_with(result)

    assert result.subscription_id == "existing-subscription"
    assert result.expiration_datetime == renewed_expiration
    assert result.client_state == "polis-teams-transcript"
    assert result.updated_at == now