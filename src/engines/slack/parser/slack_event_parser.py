"""
Parses Slack API models into Slack DTOs.
"""

from __future__ import annotations

from interfaces.api.models import (
    SlackEventRequest,
)

from engines.slack.dto import (
    SlackMessage,
)
class SlackEventParser:
    """
    Converts raw Slack Events API payloads
    into SlackMessage DTOs.
    """
    def parse(
        self,
        payload: SlackEventRequest,
    ) -> SlackMessage:
        """
        Parse a Slack webhook payload.
        """
        event = payload.event

        return SlackMessage(
            user=event.user,
            channel=event.channel,
            text=event.text,
            ts=event.ts,
            event_ts=event.event_ts,
            thread_ts=event.thread_ts,
        )