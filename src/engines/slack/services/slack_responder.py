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

    @staticmethod
    def _format_for_slack(text: str) -> str:
        """Convert supported Markdown formatting to Slack mrkdwn."""
        import re

        # Protect inline and fenced code from formatting transformations.
        code_pattern = re.compile(r"(```[\s\S]*?```|`[^`]*`)")
        parts = code_pattern.split(text)

        for index in range(0, len(parts), 2):
            segment = parts[index]

            segment = re.sub(
                r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                r"<\2|\1>",
                segment,
            )
            segment = re.sub(r"\*\*(.+?)\*\*", r"*\1*", segment)
            segment = re.sub(r"~~(.+?)~~", r"~\1~", segment)

            parts[index] = segment

        return "".join(parts)

    def reply(
        self,
        channel: str,
        thread_ts: str,
        text: str,
    ) -> None:
        """
        Reply inside the same Slack thread using Slack-compatible formatting.
        """
        self._client.post_message(
            channel=channel,
            text=self._format_for_slack(text),
            thread_ts=thread_ts,
        )

    def send_dm(
        self,
        user_id: str,
        text: str,
    ) -> str:
        """
        Send a direct message privately to a Slack user.
        Returns the DM channel ID.
        """
        return self._client.send_dm(
            user_id=user_id,
            text=text,
        )
