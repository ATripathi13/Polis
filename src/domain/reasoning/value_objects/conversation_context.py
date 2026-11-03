from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


from domain.reasoning.value_objects.request_plan import (
    PendingOperation,
    parse_and_validate_iso_timestamp,
)


@dataclass(frozen=True, slots=True)
class ConversationContext:
    user_id: str
    channel_id: str
    thread_ts: str
    history: list[dict[str, Any]] = field(default_factory=list)
    channel_type: str | None = None
    pending_operation: dict[str, Any] | None = None
    is_thread: bool = False

    @property
    def expected_thread_ts(self) -> str | None:
        """
        Return the expected thread_ts for validation.
        For genuine unthreaded DMs, returns None.
        For actual threads or channel conversations, returns thread_ts.
        """
        is_dm = (
            getattr(self, "channel_type", None) == "im"
            or (isinstance(self.channel_id, str) and self.channel_id.startswith("D"))
        )
        if is_dm and not getattr(self, "is_thread", False):
            return None
        return self.thread_ts

    def add_message(
        self,
        role: str,
        content: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ConversationContext":
        if not role.strip():
            raise ValueError("Message role cannot be empty.")

        if not content.strip():
            raise ValueError("Message content cannot be empty.")

        message: dict[str, Any] = {
            "role": role,
            "content": content,
        }

        if user_id:
            message["user_id"] = user_id

        if metadata:
            message.update(metadata)

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
            pending_operation=self.pending_operation,
            is_thread=self.is_thread,
        )

    def with_pending_operation(
        self,
        pending: dict[str, Any] | Any | None,
    ) -> "ConversationContext":
        """
        Return a new context with updated pending operation state.
        """
        pending_dict = None
        if pending is not None:
            if hasattr(pending, "model_dump"):
                pending_dict = pending.model_dump()
            elif isinstance(pending, dict):
                pending_dict = dict(pending)

        return ConversationContext(
            user_id=self.user_id,
            channel_id=self.channel_id,
            thread_ts=self.thread_ts,
            history=self.history,
            channel_type=self.channel_type,
            pending_operation=pending_dict,
            is_thread=self.is_thread,
        )

    def clear_pending_operation(self) -> "ConversationContext":
        """
        Return a new context with pending operation cleared.
        """
        return ConversationContext(
            user_id=self.user_id,
            channel_id=self.channel_id,
            thread_ts=self.thread_ts,
            history=self.history,
            channel_type=self.channel_type,
            pending_operation=None,
            is_thread=self.is_thread,
        )

    def _resolve_raw_pending_operation(
        self,
        expected_user_id: str | None = None,
    ) -> dict[str, Any] | None:
        op = self.pending_operation
        if isinstance(op, PendingOperation):
            op = op.model_dump()
        req_user = expected_user_id or self.user_id

        is_foreign_context = bool(self.user_id and req_user and self.user_id != req_user)
        is_foreign_op = bool(isinstance(op, dict) and op.get("user_id") and req_user and op.get("user_id") != req_user)

        if is_foreign_context or is_foreign_op:
            found_op = None
            if self.history:
                for message in reversed(self.history):
                    if message.get("role") == "assistant" and "pending_operation" in message:
                        msg_user = message.get("user_id")
                        if msg_user and req_user and msg_user != req_user:
                            continue
                        cand = message.get("pending_operation")
                        if cand is None:
                            # A None pending_operation explicitly clears prior pending operations for this user
                            break
                        if isinstance(cand, PendingOperation):
                            cand = cand.model_dump()
                        if isinstance(cand, dict):
                            cand_user = cand.get("user_id")
                            if not cand_user or not req_user or cand_user == req_user:
                                found_op = cand
                                break
            return found_op

        return op

    def get_typed_pending_operation(
        self,
        now: datetime | None = None,
        expected_user_id: str | None = None,
        expected_channel_id: str | None = None,
        expected_thread_ts: str | None = None,
    ) -> PendingOperation | None:
        """
        Retrieve active pending operation validated as a typed PendingOperation model.
        """
        op = self._resolve_raw_pending_operation(expected_user_id=expected_user_id)
        if not op or not isinstance(op, dict):
            return None

        # Scope validation: user_id, channel_id, thread_ts
        req_user = expected_user_id or self.user_id
        initiating_user = op.get("user_id")
        if not initiating_user or (req_user and initiating_user != req_user):
            return None

        req_channel = expected_channel_id or self.channel_id
        op_channel = op.get("channel_id")
        if req_channel and op_channel and op_channel != req_channel:
            return None
        if expected_channel_id and not op_channel:
            return None

        is_dm = (
            getattr(self, "channel_type", None) == "im"
            or (isinstance(self.channel_id, str) and self.channel_id.startswith("D"))
            or (isinstance(req_channel, str) and req_channel.startswith("D"))
        )

        is_unthreaded_dm = is_dm and not getattr(self, "is_thread", False)

        # For genuine unthreaded DMs, do not treat message timestamps as thread identifiers
        if is_unthreaded_dm and (expected_thread_ts is None or expected_thread_ts == self.thread_ts):
            pass
        else:
            req_thread = expected_thread_ts or self.thread_ts
            op_thread = op.get("thread_ts")
            if req_thread and op_thread and op_thread != req_thread:
                return None
            if not is_dm:
                if expected_thread_ts and not op_thread:
                    return None

        # Validate against typed PendingOperation model
        try:
            typed_op = PendingOperation.model_validate(op)
        except Exception:
            return None

        # Expiry validation
        current_time = now or datetime.now(timezone.utc)
        try:
            expires_at = parse_and_validate_iso_timestamp(typed_op.expires_at_iso, "expires_at_iso")
            if current_time >= expires_at:
                return None
        except Exception:
            return None

        return typed_op

    def get_pending_operation(
        self,
        now: datetime | None = None,
        expected_user_id: str | None = None,
        expected_channel_id: str | None = None,
        expected_thread_ts: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve active pending operation as a serializable dictionary,
        verifying expiration, format, and ownership scoping.
        """
        typed_op = self.get_typed_pending_operation(
            now=now,
            expected_user_id=expected_user_id,
            expected_channel_id=expected_channel_id,
            expected_thread_ts=expected_thread_ts,
        )
        if typed_op is None:
            return None
        return typed_op.model_dump()

    def add_exchange(
        self,
        user_message: str,
        assistant_message: str,
        user_id: str | None = None,
        pending_operation: dict[str, Any] | Any | None = None,
        clear_pending: bool = False,
    ) -> "ConversationContext":
        effective_user_id = user_id or self.user_id

        # Determine next pending operation
        next_pending = None
        if not clear_pending:
            if pending_operation is not None:
                if hasattr(pending_operation, "model_dump"):
                    next_pending = pending_operation.model_dump()
                elif isinstance(pending_operation, dict):
                    next_pending = dict(pending_operation)
            elif self.pending_operation is not None:
                if hasattr(self.pending_operation, "model_dump"):
                    next_pending = self.pending_operation.model_dump()
                elif isinstance(self.pending_operation, dict):
                    next_pending = dict(self.pending_operation)

        # Prevent duplicate recording of the exact same exchange, only if pending state has NOT changed
        if (
            len(self.history) >= 2
            and self.history[-2].get("role") == "user"
            and self.history[-2].get("content") == user_message
            and self.history[-2].get("user_id") == effective_user_id
            and self.history[-1].get("role") == "assistant"
            and self.history[-1].get("content") == assistant_message
        ):
            last_pending = self.history[-1].get("pending_operation")
            if last_pending == next_pending and self.pending_operation == next_pending:
                return self

        # Always include resulting pending state in assistant metadata
        assistant_metadata = {
            "pending_operation": next_pending,
        }

        context = self.add_message(
            role="user",
            content=user_message,
            user_id=effective_user_id,
        )

        updated_context = context.add_message(
            role="assistant",
            content=assistant_message,
            user_id=effective_user_id,
            metadata=assistant_metadata,
        )

        return ConversationContext(
            user_id=self.user_id,
            channel_id=self.channel_id,
            thread_ts=self.thread_ts,
            history=updated_context.history,
            channel_type=self.channel_type,
            pending_operation=next_pending,
            is_thread=self.is_thread,
        )