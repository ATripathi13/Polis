"""
Unit tests for Slack connector models.
"""

from connectors.slack.models import (
    SlackChannel,
    SlackEvent,
    SlackMessage,
    SlackUser,
)


def test_create_slack_user() -> None:
    user = SlackUser(
        user_id="U123456",
        username="john",
        email="john@example.com",
    )

    assert user.user_id == "U123456"
    assert user.username == "john"
    assert user.email == "john@example.com"


def test_create_slack_channel() -> None:
    channel = SlackChannel(
        channel_id="C123456",
        name="general",
        is_private=False,
    )

    assert channel.channel_id == "C123456"
    assert channel.name == "general"
    assert channel.is_private is False


def test_create_private_channel() -> None:
    channel = SlackChannel(
        channel_id="C999999",
        name="leadership",
        is_private=True,
    )

    assert channel.is_private is True


def test_create_slack_message() -> None:
    message = SlackMessage(
        text="Hello Polis!",
        ts="1712345678.123456",
    )

    assert message.text == "Hello Polis!"
    assert message.ts == "1712345678.123456"
    assert message.thread_ts is None


def test_create_threaded_message() -> None:
    message = SlackMessage(
        text="Reply message",
        ts="1712345679.000001",
        thread_ts="1712345678.123456",
    )

    assert message.thread_ts == "1712345678.123456"


def test_create_slack_event() -> None:

    user = SlackUser(
        user_id="U123456",
        username="john",
        email="john@example.com",
    )

    channel = SlackChannel(
        channel_id="C123456",
        name="general",
    )

    message = SlackMessage(
        text="Hello Polis!",
        ts="1712345678.123456",
    )

    event = SlackEvent(
        user=user,
        channel=channel,
        message=message,
    )

    assert event.user.user_id == "U123456"
    assert event.channel.channel_id == "C123456"
    assert event.message.text == "Hello Polis!"


def test_event_contains_thread_message() -> None:

    user = SlackUser(
        user_id="U123456",
    )

    channel = SlackChannel(
        channel_id="C123456",
    )

    message = SlackMessage(
        text="Reply",
        ts="1712345678.000001",
        thread_ts="1712345678.123456",
    )

    event = SlackEvent(
        user=user,
        channel=channel,
        message=message,
    )

    assert event.message.thread_ts == "1712345678.123456"


def test_models_are_mutable() -> None:
    """
    Connector models are transport models,
    not domain models, so mutability is allowed.
    """

    user = SlackUser(user_id="U1")

    user.username = "alice"

    assert user.username == "alice"