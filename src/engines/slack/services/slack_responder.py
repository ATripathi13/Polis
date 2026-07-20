"""
Slack response service.
"""

from __future__ import annotations

from .slack_client import (
    SlackClient,
)

class SlackResponder:
    """
    Sends responses back to Slack.
    """
    def __init__(
        self,
        client: SlackClient,
    ) -> None:

        self._client = client

    def reply(
        self,
        channel: str,
        thread_ts: str,
        text: str,
    ) -> None:
        """
        Reply inside the same Slack thread.
        """
        self._client.post_message(
            channel=channel,
            text=text,
            thread_ts=thread_ts,
        )