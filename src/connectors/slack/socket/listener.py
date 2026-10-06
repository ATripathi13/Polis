"""
Slack Socket Mode listener.
"""

from __future__ import annotations

import logging
import os
import asyncio
import re
import threading
import time
from datetime import datetime, timezone
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from application.activity import ActivityProcessor
from domain.reminders.services.reminder_service import ReminderService

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
from api.dependencies import (
    get_conversation_repository,
)
from infrastructure.config.settings import get_settings

from application.knowledge_base import (
    KnowledgeBaseIngestionService,
)

from pathlib import Path
import tempfile

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
        knowledge_base_ingestion_service: KnowledgeBaseIngestionService | None = None,
        reminder_service: ReminderService | None = None,
    ) -> None:
        self._slack_service = slack_service
        self._activity_processor = activity_processor
        self._knowledge_base_ingestion_service = (
            knowledge_base_ingestion_service
        )
        self._reminder_service = reminder_service
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

        self._slack_client = SlackClient()

        self._responder = SlackResponder(
            self._slack_client,
        )

        self._conversation_repository = get_conversation_repository()

        self._intent_router = SlackIntentRouter(
            engine=self._slack_service._cognitive_engine,
            responder=self._responder,
            connector=self._connector,
            conversation_repository=self._conversation_repository,
            identity_service=self._identity_service,
        )

        self._register_handlers()

    def _register_handlers(self) -> None:
        @self._app.event("message")
        async def handle_message(event, say):
            # Ignore bot messages to prevent loops.
            if event.get("bot_id"):
                return

            # Ignore message subtypes except file shares.
            if event.get("subtype") and event.get("subtype") != "file_share":
                return

            user_id = event.get("user")
            channel_id = event.get("channel")
            text = event.get("text", "")
            ts = event.get("ts")
            thread_ts = event.get("thread_ts")
            files = event.get("files", [])

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
            #
            # POLIS only responds when explicitly mentioned.
            # All Slack messages are still ingested and processed
            # above so they remain available for organizational memory.
            # ======================================================

            settings = get_settings()
            bot_user_id = settings.slack_bot_user_id

            mention_token = f"<@{bot_user_id}>"
            is_polis_mentioned = mention_token in text

            if not is_polis_mentioned:
                logger.info(
                    "Slack message learned without POLIS response",
                    extra={
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "user_name": user_name,
                        "message_ts": ts,
                    },
                )
                return
            # ======================================================
            # Knowledge Base file ingestion.
            #
            # A file is ingested only when POLIS is explicitly
            # mentioned in the same Slack message.
            # ======================================================

            if files and self._knowledge_base_ingestion_service is not None:
                supported_mime_types = {
                    ".pdf": "application/pdf",
                    ".docx": (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    ".txt": "text/plain",
                    ".md": "text/markdown",
                }

                for file_info in files:
                    file_id = file_info.get("id")

                    if not file_id:
                        continue

                    file_name = (
                        file_info.get("name")
                        or f"slack-{file_id}"
                    )

                    try:
                        slack_file = (
                            self._slack_client.get_file_info(
                                file_id
                            )
                        )

                        file_name = (
                            slack_file.get("name")
                            or file_info.get("name")
                            or f"slack-{file_id}"
                        )

                        file_path_name = Path(
                            file_name
                        ).name

                        suffix = Path(
                            file_path_name
                        ).suffix.lower()

                        mime_type = supported_mime_types.get(
                            suffix
                        )

                        if mime_type is None:
                            self._responder.reply(
                                channel=channel_id,
                                thread_ts=thread_ts or ts,
                                text=(
                                    f"I can't ingest "
                                    f"`{file_path_name}`. "
                                    "Supported formats are PDF, "
                                    "DOCX, TXT, and Markdown."
                                ),
                            )
                            continue

                        download_url = (
                            slack_file.get(
                                "url_private_download"
                            )
                            or slack_file.get(
                                "url_private"
                            )
                        )

                        if not download_url:
                            raise RuntimeError(
                                "Slack file has no download URL."
                            )

                        file_data = (
                            self._slack_client.download_file(
                                download_url
                            )
                        )

                        with tempfile.TemporaryDirectory() as temp_dir:
                            temp_path = (
                                Path(temp_dir)
                                / file_path_name
                            )

                            temp_path.write_bytes(
                                file_data
                            )

                            is_employee_profile = (
                                "employee profile"
                                in text.replace(
                                    mention_token,
                                    "",
                                ).lower()
                            )

                            document_metadata = None

                            if is_employee_profile:
                                document_metadata = {
                                    "knowledge_type": "employee_profile",
                                    "employee_slack_user_id": user_id,
                                }

                            document = await asyncio.to_thread(
                                self
                                ._knowledge_base_ingestion_service
                                .ingest,
                                temp_path,
                                name=file_path_name,
                                mime_type=mime_type,
                                metadata=document_metadata,
                            )

                        self._responder.reply(
                            channel=channel_id,
                            thread_ts=thread_ts or ts,
                            text=(
                                f"Knowledge Base updated successfully "
                                f"with `{file_path_name}`."
                                f"\nStatus: {document.status}"
                            ),
                        )

                    except Exception:
                        logger.exception(
                            "Failed to ingest Slack file",
                            extra={
                                "file_id": file_id,
                                "channel_id": channel_id,
                                "user_id": user_id,
                            },
                        )

                        self._responder.reply(
                            channel=channel_id,
                            thread_ts=thread_ts or ts,
                            text=(
                                f"I couldn't ingest "
                                f"`{file_name}`. "
                                "Please check that the file is readable "
                                "and try again."
                            ),
                        )

                return
            clean_text = text.replace(mention_token, "").strip()

            # ======================================================
            # Reminder commands.
            #
            # These must be handled before the normal intent router
            # so reminder requests are not interpreted as cognitive
            # questions.
            # ======================================================

            if self._reminder_service is not None:
                if clean_text.lower() == "stop":
                    stopped_count = (
                        self._reminder_service.stop_for_target(
                            user_id,
                        )
                    )

                    self._responder.reply(
                        channel=channel_id,
                        thread_ts=thread_ts or ts,
                        text=(
                            f"Stopped {stopped_count} active reminder"
                            f"{'' if stopped_count == 1 else 's'}."
                        ),
                    )
                    return

                reminder_match = re.match(
                    r"^remind\s+(.+?)\s+to\s+(.+)$",
                    clean_text,
                    re.IGNORECASE,
                )

                if reminder_match:
                    target_text = reminder_match.group(1).strip()
                    task = reminder_match.group(2).strip()

                    target_user_id = None

                    mention_match = re.fullmatch(
                        r"<@([A-Z0-9]+)>",
                        target_text,
                    )

                    if mention_match:
                        target_user_id = mention_match.group(1)
                    else:
                        target_user_id = (
                            self._identity_service.resolve_user(
                                target_text,
                            )
                        )

                    if not target_user_id:
                        self._responder.reply(
                            channel=channel_id,
                            thread_ts=thread_ts or ts,
                            text=(
                                f"I couldn't uniquely resolve "
                                f"`{target_text}` to a Slack user."
                            ),
                        )
                        return

                    settings = get_settings()

                    self._reminder_service.create(
                        target_user_id=target_user_id,
                        creator_user_id=user_id,
                        task=task,
                        channel_id=channel_id,
                        source_message_ts=ts,
                        source_thread_ts=thread_ts,
                        timezone_name=settings.reminder_timezone,
                        time_1=settings.reminder_time_1,
                        time_2=settings.reminder_time_2,
                    )

                    self._responder.reply(
                        channel=channel_id,
                        thread_ts=thread_ts or ts,
                        text=(
                            "Reminder created. "
                            f"I'll remind <@{target_user_id}> twice daily "
                            f"about: {task}"
                        ),
                    )
                    return

            activity_message = ActivitySlackMessage(
                user=activity_message.user,
                channel=activity_message.channel,
                text=clean_text,
                ts=activity_message.ts,
                event_ts=activity_message.event_ts,
                thread_ts=activity_message.thread_ts,
                user_name=activity_message.user_name,
                metadata=activity_message.metadata,
            )

            try:
                self._intent_router.handle(
                    activity_message,
                )

                logger.info(
                    "Slack intent handled for explicit POLIS mention",
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

    def _run_reminder_worker(self) -> None:
        while True:
            try:
                if self._reminder_service is not None:
                    due_reminders = self._reminder_service.find_due()

                    for reminder in due_reminders:
                        try:
                            dm_channel = self._slack_client.open_dm(
                                reminder.target_user_id,
                            )

                            self._slack_client.post_message(
                                channel=dm_channel,
                                text=f"Reminder: {reminder.task}",
                            )

                            sent_at = datetime.now(timezone.utc)
                            settings = get_settings()

                            next_reminder_at = (
                                ReminderService.next_reminder_time(
                                    now=sent_at,
                                    timezone_name=settings.reminder_timezone,
                                    time_1=settings.reminder_time_1,
                                    time_2=settings.reminder_time_2,
                                )
                            )

                            self._reminder_service.mark_sent(
                                reminder,
                                last_sent_at=sent_at,
                                next_reminder_at=next_reminder_at,
                            )

                            logger.info(
                                "Reminder delivered",
                                extra={
                                    "reminder_id": str(reminder.graph_id),
                                    "target_user_id": reminder.target_user_id,
                                },
                            )

                        except Exception:
                            logger.exception(
                                "Failed to deliver reminder %s",
                                reminder.graph_id,
                            )

            except Exception:
                logger.exception(
                    "Reminder worker iteration failed",
                )

            time.sleep(30)

    async def start(self) -> None:
        """Start Slack Socket Mode."""
        logger.info(
            "Starting Slack Socket Mode listener",
        )

        reminder_worker = threading.Thread(
            target=self._run_reminder_worker,
            name="polis-reminder-worker",
            daemon=True,
        )
        reminder_worker.start()

        await self._handler.start_async()

    async def stop(self) -> None:
        """Stop Slack Socket Mode."""
        await self._handler.close_async()
