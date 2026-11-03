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
        ctx = self._conversations.get((channel_id, thread_ts))
        if ctx is None:
            return None

        # Reconstruct pending operation from history to ensure identical behavior with PostgreSQL
        pending_operation = ctx.pending_operation
        if ctx.history:
            for message in reversed(ctx.history):
                if message.get("role") == "assistant" and "pending_operation" in message:
                    pending_operation = message.get("pending_operation")
                    break

        return ConversationContext(
            user_id=ctx.user_id,
            channel_id=ctx.channel_id,
            thread_ts=ctx.thread_ts,
            history=ctx.history,
            channel_type=ctx.channel_type,
            pending_operation=pending_operation,
        )

    def save(
        self,
        context: ConversationContext,
    ) -> ConversationContext:
        key = (context.channel_id, context.thread_ts)
        existing = self._conversations.get(key)
        if existing:
            merged_history = merge_conversation_histories(
                existing.history or [],
                context.history or [],
            )
            pending_op = context.pending_operation
            if pending_op is None and existing.pending_operation is not None:
                last_msg = context.history[-1] if context.history else {}
                if not last_msg.get("clear_pending", False):
                    if existing.get_pending_operation() is not None:
                        pending_op = existing.pending_operation

            context = ConversationContext(
                user_id=context.user_id,
                channel_id=context.channel_id,
                thread_ts=context.thread_ts,
                history=merged_history,
                channel_type=context.channel_type,
                pending_operation=pending_op,
            )

        self._conversations[key] = context
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

            pending_operation = ctx.pending_operation
            if history:
                for message in reversed(history):
                    if message.get("role") == "assistant" and "pending_operation" in message:
                        pending_operation = message.get("pending_operation")
                        break

            return ConversationContext(
                user_id=ctx.user_id,
                channel_id=ctx.channel_id,
                thread_ts=ctx.thread_ts,
                history=history,
                channel_type=ctx.channel_type,
                pending_operation=pending_operation,
            )

        return None


def _extract_message_timestamp(msg: dict[str, Any]) -> float:
    ts_val = msg.get("ts") or msg.get("event_ts")
    if ts_val:
        try:
            return float(ts_val)
        except (ValueError, TypeError):
            pass
    return 0.0


def _message_identity(msg: dict[str, Any]) -> tuple:
    role = msg.get("role", "")
    content = str(msg.get("content", "")).strip()
    user_id = msg.get("user_id", "")
    ts = msg.get("ts") or msg.get("event_ts")
    if ts:
        return (role, str(ts), content)
    return (role, user_id, content)


def merge_conversation_histories(
    existing_history: list[dict[str, Any]],
    incoming_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not existing_history:
        return list(incoming_history)
    if not incoming_history:
        return list(existing_history)

    # Fast path: If incoming already contains existing as prefix
    if len(incoming_history) >= len(existing_history):
        if incoming_history[:len(existing_history)] == existing_history:
            return list(incoming_history)

    existing_keys = set()
    for m in existing_history:
        existing_keys.add(_message_identity(m))

    merged = list(existing_history)
    for m in incoming_history:
        key = _message_identity(m)
        if key not in existing_keys:
            merged.append(m)
            existing_keys.add(key)

    # Chronological sort of exchanges if any timestamps are present
    if any(_extract_message_timestamp(m) > 0 for m in merged):
        exchanges: list[list[dict[str, Any]]] = []
        current_exchange: list[dict[str, Any]] = []
        for m in merged:
            if m.get("role") == "user" and current_exchange:
                exchanges.append(current_exchange)
                current_exchange = [m]
            else:
                current_exchange.append(m)
        if current_exchange:
            exchanges.append(current_exchange)

        def exchange_sort_key(ex: list[dict[str, Any]]) -> float:
            for item in ex:
                ts = _extract_message_timestamp(item)
                if ts > 0:
                    return ts
            return 0.0

        if any(exchange_sort_key(ex) > 0 for ex in exchanges):
            exchanges.sort(key=exchange_sort_key)

        flattened: list[dict[str, Any]] = []
        for ex in exchanges:
            flattened.extend(ex)
        return flattened

    return merged
