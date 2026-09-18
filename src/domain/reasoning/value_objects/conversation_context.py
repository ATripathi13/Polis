from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ConversationContext:
    user_id: str
    channel_id: str
    thread_ts: str
    history: list[dict[str, str]] = field(default_factory=list)

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

        message = {
            "role": role,
            "content": content,
        }

        if role == "user" and user_id:
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
        )

    def add_exchange(
        self,
        user_message: str,
        assistant_message: str,
    ) -> "ConversationContext":
        context = self.add_message(
            role="user",
            content=user_message,
            user_id=self.user_id,
        )

        return context.add_message(
            role="assistant",
            content=assistant_message,
        )