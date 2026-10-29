from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ConversationContext:
    user_id: str
    channel_id: str
    thread_ts: str
    history: list[dict[str, str]] = field(default_factory=list)
    channel_type: str | None = None

    def add_message(
        self,
        role: str,
        content: str,
        user_id: str | None = None,
    ) -> "ConversationContext":
        if not role.strip():
            raise ValueError("Message role cannot be empty.")

        if not content.strip():
            raise ValueError("Message content cannot be empty.")

        message: dict[str, str] = {
            "role": role,
            "content": content,
        }

        if user_id:
            message["user_id"] = user_id

        updated_history = [
            *self.history,
            message,
        ]

        return ConversationContext(
            user_id=self.user_id,
            channel_id=self.channel_id,
            thread_ts=self.thread_ts,
            history=updated_history,
            channel_type=self.channel_type,
        )

    def add_exchange(
        self,
        user_message: str,
        assistant_message: str,
        user_id: str | None = None,
    ) -> "ConversationContext":
        effective_user_id = user_id or self.user_id

        # Prevent duplicate recording of the exact same exchange
        if (
            len(self.history) >= 2
            and self.history[-2].get("role") == "user"
            and self.history[-2].get("content") == user_message
            and self.history[-2].get("user_id") == effective_user_id
            and self.history[-1].get("role") == "assistant"
            and self.history[-1].get("content") == assistant_message
        ):
            return self

        context = self.add_message(
            role="user",
            content=user_message,
            user_id=effective_user_id,
        )

        return context.add_message(
            role="assistant",
            content=assistant_message,
            user_id=effective_user_id,
        )