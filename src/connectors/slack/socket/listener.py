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
from application.calendar import CalendarAgent
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
from engines.slack.router.slack_intent_router import _sanitize_error_message
from engines.slack.services import (
    SlackClient,
    SlackIdentityService,
    SlackResponder,
)
from infrastructure.config.settings import get_settings

from connectors.slack.routing import (
    EventDeduplicator,
    clean_slack_text,
    is_bot_mentioned,
    is_direct_message,
)
from domain.reasoning.repositories import (
    ConversationRepository,
)
from domain.reasoning.value_objects import (
    ConversationContext,
)

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
        calendar_agent: CalendarAgent | None = None,
        conversation_repository: ConversationRepository | None = None,
        intent_router: SlackIntentRouter | None = None,
    ) -> None:
        self._slack_service = slack_service
        self._activity_processor = activity_processor
        self._knowledge_base_ingestion_service = (
            knowledge_base_ingestion_service
        )
        self._reminder_service = reminder_service
        self._calendar_agent = calendar_agent
        self._identity_service = SlackIdentityService()
        self._deduplicator = EventDeduplicator()
        self._lifecycle_state: str = "initialized"
        self._stop_event: threading.Event = threading.Event()
        self._reminder_worker_thread: threading.Thread | None = None

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

        if conversation_repository is not None:
            self._conversation_repository = conversation_repository
        else:
            from api.dependencies import get_conversation_repository

            self._conversation_repository = get_conversation_repository()

        if intent_router is not None:
            self._intent_router = intent_router
        else:
            self._intent_router = SlackIntentRouter(
                engine=self._slack_service._cognitive_engine,
                responder=self._responder,
                connector=self._connector,
                conversation_repository=self._conversation_repository,
                identity_service=self._identity_service,
            )

        self._register_handlers()

    def _register_handlers(self) -> None:
        async def handle_message(event, say=None):
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

            settings = get_settings()
            bot_user_id = settings.slack_bot_user_id

            # Ignore messages authored by POLIS itself to prevent self-reply loops.
            if bot_user_id and user_id == bot_user_id:
                return

            # Prevent duplicate processing of retried or multi-subscribed events.
            if self._deduplicator.is_duplicate(channel_id, ts):
                logger.info(
                    "Ignoring duplicate Slack event: channel=%s, ts=%s",
                    channel_id,
                    ts,
                )
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

            verified_members = None
            try:
                verified_members = await asyncio.to_thread(
                    self._identity_service.get_conversation_members,
                    channel_id,
                )
            except Exception:
                logger.warning(
                    "Failed to verify Slack conversation membership for channel %s",
                    channel_id,
                    exc_info=True,
                )

            slack_event = SlackEvent(
                user=SlackUser(
                    user_id=user_id,
                    username=user_name,
                    email=None,
                ),
                channel=SlackChannel(
                    channel_id=channel_id,
                    name=None,
                    is_private=False,
                    members=verified_members,
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
            # POLIS responds:
            # 1. In 1-to-1 Direct Messages (DMs) without requiring a mention.
            # 2. When explicitly mentioned (@POLIS or bot user id).
            # 3. In established POLIS conversation threads without requiring repeat mentions.
            #
            # All other Slack messages are still ingested and processed
            # above so they remain available for organizational memory.
            # ======================================================

            settings = get_settings()
            bot_user_id = settings.slack_bot_user_id

            is_direct = is_direct_message(
                event=event,
                channel_id=channel_id,
            )
            is_polis_mentioned = is_bot_mentioned(
                text=text,
                bot_user_id=bot_user_id,
            )

            is_established_thread = False
            if thread_ts and self._conversation_repository is not None:
                try:
                    existing_context = self._conversation_repository.get(
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                    )
                    if (
                        existing_context is not None
                        and any(msg.get("role") == "assistant" for msg in existing_context.history)
                    ):
                        is_established_thread = True
                except Exception:
                    logger.warning(
                        "Failed to check established thread state",
                        extra={
                            "operation": "check_established_thread",
                            "channel_id": channel_id,
                            "thread_ts": thread_ts,
                        },
                    )
                    is_established_thread = False

            if not (is_direct or is_polis_mentioned or is_established_thread):
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

            clean_text = clean_slack_text(
                text=text,
                bot_user_id=bot_user_id,
            )

            # ======================================================
            # Knowledge Base file ingestion.
            #
            # A file is ingested when POLIS is explicitly mentioned
            # or in a 1-to-1 Direct Message conversation.
            # ======================================================

            if files and self._knowledge_base_ingestion_service is not None and (is_polis_mentioned or is_direct):
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
                                in clean_text.lower()
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

            if not clean_text:
                logger.info(
                    "Slack message has no actionable text; skipping reply",
                    extra={
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "message_ts": ts,
                    },
                )
                return

            from application.activity import ActivityDetector

            activity_detector = getattr(self._activity_processor, "detector", None)
            if not isinstance(activity_detector, ActivityDetector):
                activity_detector = ActivityDetector()
            detected_activity = activity_detector.detect(clean_text) or activity_detector.detect(text)
            actionable_text = clean_text
            if (
                detected_activity is not None
                and getattr(detected_activity, "has_substantive_query", False) is True
                and isinstance(getattr(detected_activity, "substantive_query", None), str)
            ):
                actionable_text = clean_slack_text(
                    text=detected_activity.substantive_query,
                    bot_user_id=bot_user_id,
                )

            # ======================================================
            # Reminder commands.
            #
            # These must be handled before the normal intent router
            # so reminder requests are not interpreted as cognitive
            # questions.
            # ======================================================

            if self._reminder_service is not None:
                if actionable_text.lower() == "stop":
                    try:
                        stopped_count = (
                            self._reminder_service.stop_for_target(
                                user_id,
                            )
                        )
                        reply_text = (
                            f"Stopped {stopped_count} active reminder"
                            f"{'' if stopped_count == 1 else 's'}."
                        )
                    except Exception:
                        logger.error(
                            "Failed to stop reminders for user",
                            extra={
                                "operation": "stop_reminders",
                                "user_id": user_id,
                            },
                        )
                        reply_text = (
                            "I encountered an error while trying to stop reminders. "
                            "Please try again later."
                        )

                    reply_thread_ts = thread_ts or ts
                    self._record_conversation_exchange(
                        channel_id=channel_id,
                        thread_ts=reply_thread_ts,
                        user_id=user_id,
                        user_message=text,
                        assistant_message=reply_text,
                        is_thread=bool(thread_ts),
                    )
                    self._responder.reply(
                        channel=channel_id,
                        thread_ts=reply_thread_ts,
                        text=reply_text,
                    )
                    return

                reminder_match = re.match(
                    r"^remind\s+(.+?)\s+to\s+(.+)$",
                    actionable_text,
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

                    try:
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
                        reply_text = (
                            "Done! I've set a reminder. "
                            f"I'll remind <@{target_user_id}> twice daily "
                            f"about: {task}"
                        )
                    except Exception:
                        logger.error(
                            "Failed to create reminder for user",
                            extra={
                                "operation": "create_reminder",
                                "target_user_id": target_user_id,
                            },
                        )
                        reply_text = (
                            "I encountered an error while trying to set that reminder. "
                            "Please try again later."
                        )

                    reply_thread_ts = thread_ts or ts
                    self._record_conversation_exchange(
                        channel_id=channel_id,
                        thread_ts=reply_thread_ts,
                        user_id=user_id,
                        user_message=text,
                        assistant_message=reply_text,
                        is_thread=bool(thread_ts),
                    )
                    self._responder.reply(
                        channel=channel_id,
                        thread_ts=reply_thread_ts,
                        text=reply_text,
                    )
                    return

            # Handle calendar commands deterministically before the
            # general-purpose intent router.
            if self._calendar_agent is not None:
                try:
                    title_field_present = bool(
                        re.search(r"(?im)^\s*[-*•]?\s*Title\s*:", actionable_text)
                    )
                    extracted_title_present = bool(
                        self._calendar_agent._extract_title(actionable_text)
                    )
                    calendar_response = self._calendar_agent.handle_message(
                        actionable_text,
                        user_id=user_id,
                        channel_id=channel_id,
                    )
                except Exception:
                    logger.exception(
                        "Calendar agent failed to handle Slack message",
                        extra={
                            "channel_id": channel_id,
                            "user_id": user_id,
                            "message_ts": ts,
                        },
                    )
                    calendar_response = (
                        "I couldn't process that calendar request. "
                        "Please try again."
                    )

                if calendar_response is not None:
                    reply_thread_ts = thread_ts or ts
                    self._record_conversation_exchange(
                        channel_id=channel_id,
                        thread_ts=reply_thread_ts,
                        user_id=user_id,
                        user_message=text,
                        assistant_message=calendar_response,
                        is_thread=bool(thread_ts),
                    )
                    self._responder.reply(
                        channel=channel_id,
                        thread_ts=reply_thread_ts,
                        text=calendar_response,
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
                metadata={
                    **activity_message.metadata,
                    "original_text": text,
                },
            )

            try:
                self._intent_router.handle(
                    activity_message,
                )

                logger.info(
                    "Slack intent handled for message in %s",
                    channel_id,
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

        self._app.event("message")(handle_message)
        self._handle_message = handle_message

    def _record_conversation_exchange(
        self,
        channel_id: str,
        thread_ts: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
        is_thread: bool = False,
    ) -> None:
        """
        Record a conversation exchange in the repository to establish thread state.
        """
        if self._conversation_repository is None:
            return

        try:
            context = self._conversation_repository.get(
                channel_id=channel_id,
                thread_ts=thread_ts,
            )

            is_dm = channel_id.startswith("D")
            expected_thread = thread_ts if (is_thread or not is_dm) else None
            if context is None:
                context = ConversationContext(
                    user_id=user_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    channel_type="im" if is_dm else None,
                    is_thread=is_thread,
                )
            else:
                if is_dm and context.user_id and context.user_id != user_id:
                    logger.warning(
                        "Cannot record exchange in private DM owned by another user: expected %s, got %s",
                        context.user_id,
                        user_id,
                    )
                    return

                valid_pending = context.get_pending_operation(
                    expected_user_id=user_id,
                    expected_channel_id=channel_id,
                    expected_thread_ts=expected_thread,
                )
                context = ConversationContext(
                    user_id=context.user_id if is_dm else user_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    history=context.history,
                    channel_type=context.channel_type or ("im" if is_dm else None),
                    pending_operation=valid_pending,
                    is_thread=is_thread,
                )

            updated = context.add_exchange(
                user_message=user_message,
                assistant_message=assistant_message,
                user_id=user_id,
            )
            self._conversation_repository.save(updated)

        except Exception as exc:
            logger.error(
                "Failed to record conversation exchange for thread %s: %s",
                thread_ts,
                _sanitize_error_message(str(exc)),
                extra={"operation": "record_conversation_exchange", "thread_ts": thread_ts},
            )


    def _run_reminder_worker(self) -> None:
        while not self._stop_event.is_set():
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
                                    "operation": "deliver_reminder",
                                },
                            )

                        except Exception:
                            logger.error(
                                "Failed to deliver reminder",
                                extra={
                                    "reminder_id": str(reminder.graph_id),
                                    "operation": "deliver_reminder_failure",
                                },
                            )

            except Exception:
                logger.error(
                    "Reminder worker iteration failed",
                    extra={"operation": "reminder_worker_iteration_failure"},
                )

            self._stop_event.wait(timeout=30)

    async def start(self) -> None:
        """Start Slack Socket Mode."""
        self._lifecycle_state = "running"
        self._stop_event.clear()
        logger.info(
            "Starting Slack Socket Mode listener",
            extra={"operation": "start_socket_listener", "lifecycle_state": self._lifecycle_state},
        )

        self._reminder_worker_thread = threading.Thread(
            target=self._run_reminder_worker,
            name="polis-reminder-worker",
            daemon=True,
        )
        self._reminder_worker_thread.start()

        try:
            await self._handler.start_async()
        except asyncio.CancelledError:
            logger.info(
                "Slack Socket Mode handler execution cancelled",
                extra={"operation": "handler_cancelled"},
            )
            raise

    async def stop(self) -> None:
        """Stop Slack Socket Mode listener idempotently using persistent lifecycle state."""
        if self._lifecycle_state in ("stopping", "stopped"):
            logger.info(
                "Slack Socket Mode listener already in %s state; skipping stop",
                self._lifecycle_state,
                extra={"operation": "stop_socket_listener", "lifecycle_state": self._lifecycle_state},
            )
            return

        self._lifecycle_state = "stopping"
        logger.info(
            "Stopping Slack Socket Mode listener",
            extra={"operation": "stop_socket_listener", "lifecycle_state": self._lifecycle_state},
        )

        try:
            self._stop_event.set()
            if self._reminder_worker_thread is not None and self._reminder_worker_thread.is_alive():
                self._reminder_worker_thread.join(timeout=2.0)

            if self._handler is not None:
                try:
                    await self._handler.close_async()
                except Exception:
                    logger.warning(
                        "Error closing Slack Socket Mode handler",
                        extra={"operation": "close_socket_handler"},
                    )
        finally:
            self._lifecycle_state = "stopped"
            logger.info(
                "Slack Socket Mode listener stopped",
                extra={"operation": "stop_socket_listener", "lifecycle_state": self._lifecycle_state},
            )
