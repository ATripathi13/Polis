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