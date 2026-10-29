from __future__ import annotations

from abc import ABC, abstractmethod

from domain.reasoning.value_objects import ConversationContext


class ConversationRepository(ABC):
    @abstractmethod
    def get(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> ConversationContext | None:
        raise NotImplementedError

    @abstractmethod
    def save(
        self,
        context: ConversationContext,
    ) -> ConversationContext:
        raise NotImplementedError

    def get_latest(
        self,
        channel_id: str,
        user_id: str | None = None,
    ) -> ConversationContext | None:
        """
        Return the most recently updated conversation context for a channel,
        optionally restricted to contexts containing messages from user_id.
        """
        return None