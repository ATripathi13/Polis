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

from engines.slack.services import (
    SlackIdentityService,
)


class SlackEventParser:
    """
    Converts raw Slack Events API payloads
    into SlackMessage DTOs.
    """

    def __init__(
        self,
        identity_service: SlackIdentityService,
    ) -> None:

        self._identity_service = (
            identity_service
        )

    def parse(
        self,
        payload: SlackEventRequest,
    ) -> SlackMessage:
        """
        Parse a Slack webhook payload.
        """

        event = payload.event

        user_name = (
            self._identity_service
            .get_display_name(
                event.user,
            )
        )

        return SlackMessage(
            user=event.user,
            user_name=user_name,
            channel=event.channel,
            text=event.text,
            ts=event.ts,
            event_ts=event.event_ts,
            thread_ts=event.thread_ts,
        )