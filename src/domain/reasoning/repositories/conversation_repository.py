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