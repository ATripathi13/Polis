import asyncio
from unittest.mock import Mock

import pytest

from application.meetings.teams_subscription_renewal import (
    TeamsSubscriptionRenewal,
)


@pytest.mark.asyncio
async def test_renewal_checks_transcript_and_recording_services(
    monkeypatch,
):
    transcript_service = Mock()
    recording_service = Mock()

    transcript_service.ensure_subscription.return_value = Mock(
        expiration_datetime="transcript-expiry",
    )
    recording_service.ensure_subscription.return_value = Mock(
        expiration_datetime="recording-expiry",
    )

    worker = TeamsSubscriptionRenewal(
        transcript_service=transcript_service,
        recording_service=recording_service,
    )

    async def fake_sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        asyncio,
        "sleep",
        fake_sleep,
    )

    await worker.start()

    with pytest.raises(asyncio.CancelledError):
        await worker._task

    transcript_service.ensure_subscription.assert_called_once()
    recording_service.ensure_subscription.assert_called_once()