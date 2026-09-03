"""
Slack Socket Mode listener.
"""

from __future__ import annotations

import asyncio
import logging

from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from connectors.slack.models import (
    SlackEvent,
    SlackChannel,
    SlackMessage,
    SlackUser,
)
from connectors.slack.services import SlackService

logger = logging.getLogger(__name__)


class SlackSocketListener:
    """
    Receives Slack events through Socket Mode and forwards
    them into the existing Polis SlackService.
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        slack_service: SlackService,
    ) -> None:
        self._slack_service = slack_service

        self._app = AsyncApp(
            token=bot_token,
        )

        self._handler = AsyncSocketModeHandler(
            self._app,
            app_token,
        )

        self._register_handlers()

    def _register_handlers(self) -> None:
        @self._app.event("message")
        async def handle_message(event, say):
            # Ignore bot messages to prevent loops.
            if event.get("bot_id"):
                return

            # Ignore message subtypes such as joins, edits, etc.
            if event.get("subtype"):
                return

            user_id = event.get("user")
            channel_id = event.get("channel")
            text = event.get("text", "")
            ts = event.get("ts")
            thread_ts = event.get("thread_ts")

            if not user_id or not channel_id or not ts:
                return

            slack_event = SlackEvent(
                user=SlackUser(
                    user_id=user_id,
                    username=None,
                    email=None,
                ),
                channel=SlackChannel(
                    channel_id=channel_id,
                    name=None,
                    is_private=False,
                ),
                message=SlackMessage(
                    text=text,
                    ts=ts,
                    thread_ts=thread_ts,
                ),
            )

            try:
                result = self._slack_service.ingest(slack_event)

                logger.info(
                    "Slack message ingested",
                    extra={
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "message_ts": ts,
                        "correlation_id": (
                            result.correlation_id.business_id
                        ),
                    },
                )

            except Exception:
                logger.exception(
                    "Failed to ingest Slack message"
                )

    async def start(self) -> None:
        """Start Slack Socket Mode."""
        logger.info("Starting Slack Socket Mode listener")
        await self._handler.start_async()

    async def stop(self) -> None:
        """Stop Slack Socket Mode."""
        await self._handler.close_async()