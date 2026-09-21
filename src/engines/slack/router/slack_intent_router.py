"""
Routes explicit POLIS Slack messages to the conversational
cognitive engine.
"""

from __future__ import annotations

import re

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

from engines.slack.dto import (
    SlackMessage,
)

from engines.slack.services import (
    SlackIdentityService,
    SlackResponder,
)


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
    ) -> None:

        self._engine = engine

        self._responder = responder

        self._connector = connector

        self._conversation_repository = conversation_repository

        self._identity_service = (
            identity_service
            or SlackIdentityService()
        )

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

        thread_ts = message.thread_ts or message.ts

        conversation_context = self._conversation_repository.get(
            channel_id=message.channel,
            thread_ts=thread_ts,
        )

        if conversation_context is None:
            conversation_context = ConversationContext(
                user_id=message.user,
                channel_id=message.channel,
                thread_ts=thread_ts,
            )

        target_user = self._resolve_target_user(
            text=text,
            requester_user_id=message.user,
        )

        question = Question(
            text=text,
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
        )

        answer = self._engine.ask(
            question,
        )

        updated_context = conversation_context.add_exchange(
            user_message=text,
            assistant_message=answer.text,
        )

        self._conversation_repository.save(
            updated_context,
        )

        self._responder.reply(
            channel=message.channel,
            thread_ts=(
                message.thread_ts
                or message.ts
            ),
            text=answer.text,
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

        matches: list[dict] = []

        for user in users:
            if user.get("deleted"):
                continue

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