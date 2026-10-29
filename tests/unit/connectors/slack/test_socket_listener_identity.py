"""
Regression tests for Slack user identity resolution and preservation during event ingestion.
"""

from unittest.mock import MagicMock, patch
import pytest

from connectors.slack.models import (
    SlackChannel,
    SlackEvent,
    SlackMessage,
    SlackUser,
)
from connectors.slack.normalizers import SlackNormalizer
from engines.communication.domain.enums import EventSource


def test_slack_user_preserves_resolved_username_in_actor():
    """
    Verify that when SlackUser is initialized with a resolved username,
    to_actor() preserves the human display name while retaining internal_id.
    """
    user = SlackUser(
        user_id="U0BU14F6CTD",
        username="Hemant Kumar Sah",
        email="hemant@example.com",
    )

    actor = user.to_actor()

    assert actor.identity.internal_id == "U0BU14F6CTD"
    assert actor.display_name == "Hemant Kumar Sah"


def test_slack_normalizer_preserves_resolved_name():
    """
    Verify that normalizing a SlackEvent preserves the resolved human name
    on the resulting CommunicationEvent actor.
    """
    event = SlackEvent(
        user=SlackUser(
            user_id="U0BU14F6CTD",
            username="Hemant Kumar Sah",
        ),
        channel=SlackChannel(
            channel_id="C001",
            name="general",
        ),
        message=SlackMessage(
            text="I was granted calendar access recently",
            ts="1712345678.000100",
        ),
    )

    normalizer = SlackNormalizer()
    comm = normalizer.normalize(event)

    assert comm.source == EventSource.SLACK
    assert comm.actor.identity.internal_id == "U0BU14F6CTD"
    assert comm.actor.display_name == "Hemant Kumar Sah"


@pytest.mark.asyncio
async def test_listener_handler_passes_resolved_name_to_ingest():
    """
    Verify that SlackSocketListener resolves the user's display name and
    passes it into SlackUser.username when constructing the SlackEvent for ingestion.
    """
    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler"), \
         patch("connectors.slack.socket.listener.SlackConnector"), \
         patch("connectors.slack.socket.listener.SlackClient"), \
         patch("connectors.slack.socket.listener.SlackResponder"), \
         patch("connectors.slack.socket.listener.SlackIntentRouter"):

        from connectors.slack.socket.listener import SlackSocketListener

        mock_slack_service = MagicMock()
        mock_activity_processor = MagicMock()

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=mock_slack_service,
            activity_processor=mock_activity_processor,
            conversation_repository=MagicMock(),
        )

        mock_identity = MagicMock()
        mock_identity.get_display_name.return_value = "Hemant Kumar Sah"
        listener._identity_service = mock_identity

        # Find the registered handle_message handler
        handlers = listener._app.event.call_args_list
        assert len(handlers) >= 1
        assert handlers[0][0][0] == "message"

        handle_message_coro = listener._app.event.return_value.call_args[0][0]

        event_payload = {
            "user": "U0BU14F6CTD",
            "channel": "C001",
            "text": "Hello world",
            "ts": "1712345678.000100",
        }

        await handle_message_coro(event_payload, MagicMock())

        # Assert ingest was called with SlackEvent having username="Hemant Kumar Sah"
        assert mock_slack_service.ingest.called
        ingested_event: SlackEvent = mock_slack_service.ingest.call_args[0][0]
        assert isinstance(ingested_event, SlackEvent)
        assert ingested_event.user.user_id == "U0BU14F6CTD"
        assert ingested_event.user.username == "Hemant Kumar Sah"
