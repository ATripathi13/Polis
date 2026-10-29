from __future__ import annotations

from domain.reasoning.repositories.conversation_repository import (
    ConversationRepository,
)
from domain.reasoning.value_objects import ConversationContext


class InMemoryConversationRepository(
    ConversationRepository,
):
    def __init__(self) -> None:
        self._conversations: dict[
            tuple[str, str],
            ConversationContext,
        ] = {}

    def get(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> ConversationContext | None:
        return self._conversations.get(
            (channel_id, thread_ts)
        )

    def save(
        self,
        context: ConversationContext,
    ) -> ConversationContext:
        self._conversations[
            (
                context.channel_id,
                context.thread_ts,
            )
        ] = context

        return context

    def get_latest(
        self,
        channel_id: str,
        user_id: str | None = None,
    ) -> ConversationContext | None:
        contexts = list(self._conversations.values())
        for ctx in reversed(contexts):
            if ctx.channel_id != channel_id:
                continue

            history = ctx.history or []
            if user_id is not None:
                matching_user_messages = [
                    message
                    for message in history
                    if message.get("role") == "user"
                    and message.get("user_id") == user_id
                ]
                if not matching_user_messages:
                    continue

                is_dm = (
                    channel_id.startswith("D")
                    or getattr(ctx, "channel_type", None) == "im"
                )
                if is_dm and any(
                    message.get("role") == "user"
                    and message.get("user_id")
                    and message.get("user_id") != user_id
                    for message in history
                ):
                    continue

            return ctx

        return None
