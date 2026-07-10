from connectors.slack.models import (
    SlackChannel,
    SlackEvent,
    SlackMessage,
    SlackUser,
)

from connectors.slack.normalizers import SlackNormalizer

from engines.communication.domain.enums import (
    EventSource,
)


def test_normalize_slack_event():

    user = SlackUser(
        user_id="U123",
        username="john",
    )

    channel = SlackChannel(
        channel_id="C123",
        name="general",
    )

    message = SlackMessage(
        text="Hello Polis!",
        ts="1712345678.123456",
    )

    slack_event = SlackEvent(
        user=user,
        channel=channel,
        message=message,
    )

    normalizer = SlackNormalizer()

    communication = normalizer.normalize(slack_event)

    assert communication.source == EventSource.SLACK

    assert communication.actor.display_name == "john"

    assert communication.channel.name == "general"

    assert communication.content.body == "Hello Polis!"