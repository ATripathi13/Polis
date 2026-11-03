"""
Routes explicit POLIS Slack messages to the conversational
cognitive engine.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

from application.cognitive import (
    CognitiveEngine,
)

from domain.reasoning import (
    ConversationContext,
    Question,
)
from domain.reasoning.repositories import (
    ConversationRepository,
)
from application.activity import (
    ActivityDetector,
)

from engines.slack.dto import (
    SlackMessage,
)

from engines.slack.services import (
    SlackIdentityService,
    SlackResponder,
)


def _sanitize_error_message(msg: str) -> str:
    """
    Remove passwords, credentials, connection strings, and Slack tokens from error messages.
    """
    if not msg:
        return ""
    # Mask postgresql://user:password@host:port/db style URIs
    sanitized = re.sub(
        r"://([^:]+):([^@]+)@",
        r"://\1:***@",
        str(msg),
    )
    # Mask password=... in query strings or DSNs
    sanitized = re.sub(
        r"(password\s*=\s*['\"]?)[^'\"]+(['\"]?)",
        r"\1***\2",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Mask Slack tokens: xoxb-, xapp-, xoxp-, xoxa-, xoxr-, xoxs-
    sanitized = re.sub(
        r"\b(xoxb|xapp|xoxp|xoxa|xoxr|xoxs)-[A-Za-z0-9_-]+\b",
        r"\1-***",
        sanitized,
    )
    return sanitized


class SlackIntentRouter:
    """
    Routes explicitly addressed POLIS messages
    to the cognitive engine.
    """

    def __init__(
        self,
        engine: CognitiveEngine,
        responder: SlackResponder,
        connector,
        conversation_repository: ConversationRepository,
        identity_service: SlackIdentityService | None = None,
        activity_detector: ActivityDetector | None = None,
    ) -> None:

        self._engine = engine

        self._responder = responder

        self._connector = connector

        self._conversation_repository = conversation_repository

        self._identity_service = (
            identity_service
            or SlackIdentityService()
        )

        self._activity_detector = (
            activity_detector
            or ActivityDetector()
        )

    @staticmethod
    def _is_raw_user_id(val: str | None) -> bool:
        if not val:
            return True
        trimmed = val.strip()
        return bool(re.match(r"^[UW][A-Z0-9_-]{5,}$", trimmed) or re.match(r"^U_[A-Z0-9_-]+$", trimmed))

    def handle(
        self,
        message: SlackMessage,
    ) -> None:
        """
        Handle an explicit POLIS Slack message.

        The Slack listener is responsible for determining
        whether POLIS was mentioned. Once this method is
        called, the message is treated as a conversational
        request regardless of punctuation.
        """

        text = message.text.strip()

        if not text:
            return

        is_dm = message.channel.startswith("D")
        is_thread = message.thread_ts is not None

        thread_key = message.thread_ts or message.ts

        try:
            conversation_context = self._conversation_repository.get(
                channel_id=message.channel,
                thread_ts=thread_key,
            )

            if is_dm:
                expected_thread = message.thread_ts if is_thread else None
                latest_context = None
                if conversation_context is None:
                    history = []
                    if hasattr(self._conversation_repository, "get_latest"):
                        latest_context = self._conversation_repository.get_latest(
                            channel_id=message.channel,
                            user_id=message.user,
                        )
                        if latest_context is not None:
                            history = latest_context.history

                    pending_op = None
                    if latest_context is not None:
                        pending_op = latest_context.get_pending_operation(
                            expected_user_id=message.user,
                            expected_channel_id=message.channel,
                            expected_thread_ts=expected_thread,
                        )

                    conversation_context = ConversationContext(
                        user_id=message.user,
                        channel_id=message.channel,
                        thread_ts=thread_key,
                        history=history,
                        channel_type="im",
                        pending_operation=pending_op,
                        is_thread=is_thread,
                    )
                else:
                    # Enforce scope ownership for private DMs
                    if conversation_context.user_id and conversation_context.user_id != message.user:
                        conversation_context = ConversationContext(
                            user_id=message.user,
                            channel_id=message.channel,
                            thread_ts=thread_key,
                            history=[],
                            channel_type="im",
                            pending_operation=None,
                            is_thread=is_thread,
                        )
                    else:
                        valid_pending = conversation_context.get_pending_operation(
                            expected_user_id=message.user,
                            expected_channel_id=message.channel,
                            expected_thread_ts=expected_thread,
                        )
                        conversation_context = ConversationContext(
                            user_id=message.user,
                            channel_id=message.channel,
                            thread_ts=thread_key,
                            history=conversation_context.history,
                            channel_type="im",
                            pending_operation=valid_pending,
                            is_thread=is_thread,
                        )

            elif is_thread:
                # Safeguard 2: Thread context must always use the parent thread_ts, including when processing replies.
                if conversation_context is None:
                    conversation_context = ConversationContext(
                        user_id=message.user,
                        channel_id=message.channel,
                        thread_ts=thread_key,
                        history=[],
                        is_thread=True,
                    )
                else:
                    valid_pending = conversation_context.get_pending_operation(
                        expected_user_id=message.user,
                        expected_channel_id=message.channel,
                        expected_thread_ts=thread_key,
                    )
                    conversation_context = ConversationContext(
                        user_id=message.user,
                        channel_id=message.channel,
                        thread_ts=thread_key,
                        history=conversation_context.history,
                        channel_type=conversation_context.channel_type,
                        pending_operation=valid_pending,
                        is_thread=True,
                    )

            else:
                # Safeguard 5: Standalone channel messages must remain independent and must not create persistent conversational context.
                conversation_context = ConversationContext(
                    user_id=message.user,
                    channel_id=message.channel,
                    thread_ts=thread_key,
                    history=[],
                    channel_type=None,
                    pending_operation=None,
                    is_thread=False,
                )

            from application.activity import ActivityDetector

            if not isinstance(self._activity_detector, ActivityDetector):
                detector = ActivityDetector()
            else:
                detector = self._activity_detector

            detected = detector.detect(text)

            sender_display_name: str | None = None
            if (
                detected is not None
                and getattr(detected, "has_substantive_query", False) is True
                and isinstance(getattr(detected, "substantive_query", None), str)
            ):
                question_text = detected.substantive_query
                target_user = self._resolve_target_user(
                    text=question_text,
                    requester_user_id=message.user,
                )
            elif (
                detected is not None
                and getattr(detected, "is_greeting", False) is True
            ):
                question_text = text
                sender_display_name = (message.user_name or "").strip()
                if (not sender_display_name or self._is_raw_user_id(sender_display_name)) and self._identity_service:
                    try:
                        resolved_name = self._identity_service.get_display_name(message.user)
                        if resolved_name and not self._is_raw_user_id(resolved_name):
                            sender_display_name = resolved_name.strip()
                    except Exception:
                        pass
                if (not sender_display_name or self._is_raw_user_id(sender_display_name)) and self._identity_service:
                    try:
                        users = self._identity_service.get_workspace_users()
                        for u in users:
                            if u.get("id") == message.user:
                                candidate = (
                                    u.get("profile", {}).get("display_name")
                                    or u.get("real_name")
                                    or u.get("name")
                                    or ""
                                ).strip()
                                if candidate and not self._is_raw_user_id(candidate):
                                    sender_display_name = candidate
                                    break
                    except Exception:
                        pass
                if self._is_raw_user_id(sender_display_name):
                    sender_display_name = ""
                target_user = {
                    "id": None,
                    "name": sender_display_name or None,
                }
            else:
                question_text = text
                target_user = self._resolve_target_user(
                    text=text,
                    requester_user_id=message.user,
                )

            question = Question(
                text=question_text,
                context=conversation_context,
                target_user_id=(
                    target_user["id"]
                    if target_user is not None
                    else None
                ),
                target_user_name=(
                    target_user["name"]
                    if target_user is not None
                    else None
                ),
                user_id=message.user,
                user_name=sender_display_name if (detected is not None and getattr(detected, "is_greeting", False)) else (message.user_name or None),
            )

            answer = self._engine.ask(
                question,
            )

            original_user_message = message.metadata.get("original_text") or message.text

            # Only persist conversation context for DMs and established threads
            if is_dm or is_thread:
                updated_context = conversation_context.add_exchange(
                    user_message=original_user_message,
                    assistant_message=answer.text,
                    user_id=message.user,
                    pending_operation=getattr(answer, "pending_operation", None),
                    clear_pending=getattr(answer, "clear_pending", False),
                )
                try:
                    self._conversation_repository.save(
                        updated_context,
                    )
                except Exception as exc:
                    logger.exception(
                        "Failed to persist conversation context for channel %s, thread %s: %s",
                        message.channel,
                        thread_key,
                        _sanitize_error_message(str(exc)),
                    )

            self._responder.reply(
                channel=message.channel,
                thread_ts=(
                    message.thread_ts
                    or message.ts
                ),
                text=answer.text,
            )
        except Exception as exc:
            sanitized = _sanitize_error_message(str(exc))
            logger.exception(
                "Failed to process Slack message in channel %s, thread %s: %s",
                message.channel,
                thread_key,
                sanitized,
            )
            self._responder.reply(
                channel=message.channel,
                thread_ts=thread_key,
                text="I encountered an error while trying to answer that question.",
            )

    def _resolve_target_user(
        self,
        text: str,
        requester_user_id: str,
    ) -> dict[str, str] | None:
        """
        Resolve the person the question is about.

        Self-references resolve to the requesting user.
        Explicitly named workspace members are resolved
        dynamically through SlackIdentityService.

        If no unambiguous person is found, the requester
        remains the target rather than guessing another user.
        """

        normalized_text = text.lower()

        users = self._identity_service.get_workspace_users()

        # ------------------------------------------------------
        # EXPLICIT SLACK USER MENTION
        # ------------------------------------------------------

        mention_match = re.search(
            r"<@([A-Z0-9]+)(?:\|[^>]+)?>",
            text,
        )

        if mention_match:
            mentioned_user_id = mention_match.group(1)

            for user in users:
                if user.get("id") != mentioned_user_id:
                    continue

                display_name = (
                    user.get("profile", {})
                    .get("display_name")
                    or user.get("real_name")
                    or user.get("name")
                    or mentioned_user_id
                )

                return {
                    "id": mentioned_user_id,
                    "name": display_name,
                }
        matches: list[dict] = []

        for user in users:
            display_name = (
                user.get("profile", {})
                .get("display_name")
                or ""
            )

            real_name = user.get("real_name") or ""
            username = user.get("name") or ""

            candidates = {
                display_name,
                real_name,
                username,
            }

            for candidate in candidates:
                    candidate = candidate.strip()

                    if not candidate:
                        continue

                    candidate_normalized = " ".join(
                        candidate.lower().split()
                    )

                    if re.search(
                        rf"(?<!\w){re.escape(candidate_normalized)}(?!\w)",
                        normalized_text,
                    ):
                        if user not in matches:
                            matches.append(user)

                        break

        if len(matches) == 1:
            user = matches[0]

            display_name = (
                user.get("profile", {})
                .get("display_name")
                or user.get("real_name")
                or user.get("name")
                or user["id"]
            )

            return {
                "id": user["id"],
                "name": display_name,
            }

        self_references = {
            "i",
            "me",
            "my",
            "mine",
            "myself",
        }

        if any(
            re.search(
                rf"\b{re.escape(reference)}\b",
                normalized_text,
            )
            for reference in self_references
        ):
            return {
                "id": requester_user_id,
                "name": "",
            }

        return None
