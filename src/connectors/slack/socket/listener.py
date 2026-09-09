"""
Slack Socket Mode listener.
"""

from __future__ import annotations

import logging
import os

from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from application.activity import ActivityProcessor

from connectors.slack.models import (
    SlackEvent,
    SlackChannel,
    SlackMessage,
    SlackUser,
)

from connectors.slack.services import SlackService

from engines.slack.connector import SlackConnector
from engines.slack.dto import (
    SlackMessage as ActivitySlackMessage,
)
from engines.slack.mapper import CommunicationMapper
from engines.slack.router import SlackIntentRouter
from engines.slack.services import (
    SlackClient,
    SlackIdentityService,
    SlackResponder,
)

from infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


class SlackSocketListener:
    """
    Receives Slack events through Socket Mode and forwards
    them into the existing Polis SlackService,
    ActivityProcessor, and SlackIntentRouter.
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        slack_service: SlackService,
        activity_processor: ActivityProcessor,
    ) -> None:
        self._slack_service = slack_service
        self._activity_processor = activity_processor
        self._identity_service = SlackIdentityService()

        os.environ.pop("SLACK_CLIENT_ID", None)
        os.environ.pop("SLACK_CLIENT_SECRET", None)

        self._app = AsyncApp(
            token=bot_token,
        )

        self._handler = AsyncSocketModeHandler(
            self._app,
            app_token,
        )

        settings = get_settings()

        self._connector = SlackConnector(
            engine=self._slack_service._cognitive_engine,
            mapper=CommunicationMapper(),
            settings=settings,
            activity_processor=activity_processor,
        )

        self._responder = SlackResponder(
            SlackClient(),
        )

        self._intent_router = SlackIntentRouter(
            engine=self._slack_service._cognitive_engine,
            responder=self._responder,
            connector=self._connector,
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

            # ======================================================
            # Resolve the Slack user's human-readable name.
            # ======================================================

            try:
                user_name = self._identity_service.get_display_name(
                    user_id,
                )

            except Exception:
                logger.exception(
                    "Failed to resolve Slack user name: %s",
                    user_id,
                )
                user_name = user_id

            # ======================================================
            # Existing Slack communication event.
            # ======================================================

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

            # ======================================================
            # Activity event message.
            # ======================================================

            activity_message = ActivitySlackMessage(
                user=user_id,
                user_name=user_name,
                channel=channel_id,
                text=text,
                ts=ts,
                event_ts=ts,
                thread_ts=thread_ts,
            )

            # ======================================================
            # Existing communication / cognitive pipeline.
            # ======================================================

            try:
                result = self._slack_service.ingest(
                    slack_event,
                )

                logger.info(
                    "Slack message ingested",
                    extra={
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "user_name": user_name,
                        "message_ts": ts,
                        "correlation_id": (
                            result.correlation_id.business_id
                        ),
                    },
                )

            except Exception:
                logger.exception(
                    "Failed to ingest Slack message",
                )

            # ======================================================
            # Activity processing.
            #
            # Only explicit activity phrases are persisted.
            # Ordinary Slack messages are ignored by the detector.
            # ======================================================

            try:
                self._activity_processor.process(
                    activity_message,
                )

                logger.info(
                    "Slack activity processed",
                    extra={
                        "user_id": user_id,
                        "user_name": user_name,
                        "message_ts": ts,
                    },
                )

            except Exception:
                logger.exception(
                    "Failed to process Slack activity",
                )

            # ======================================================
            # POLIS question handling.
            # ======================================================

            try:
                self._intent_router.handle(
                    activity_message,
                )

                logger.info(
                    "Slack intent handled",
                    extra={
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "user_name": user_name,
                        "message_ts": ts,
                    },
                )

            except Exception:
                logger.exception(
                    "Failed to handle Slack intent",
                )

            return

    async def start(self) -> None:
        """Start Slack Socket Mode."""
        logger.info(
            "Starting Slack Socket Mode listener",
        )

        await self._handler.start_async()

    async def stop(self) -> None:
        """Stop Slack Socket Mode."""
        await self._handler.close_async()