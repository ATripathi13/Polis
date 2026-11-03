from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from domain.reasoning.repositories import ConversationRepository
from domain.reasoning.value_objects import ConversationContext

from .connection import SessionLocal
from .conversation_repository import merge_conversation_histories
from .models import ConversationMemoryModel


class PostgreSQLConversationRepository(
    ConversationRepository,
):
    def get(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> ConversationContext | None:
        with SessionLocal() as session:
            record = (
                session.query(ConversationMemoryModel)
                .filter(
                    ConversationMemoryModel.channel_id == channel_id,
                    ConversationMemoryModel.thread_ts == thread_ts,
                )
                .first()
            )

            if record is None:
                return None

            history = record.history or []

            user_id = ""

            for message in reversed(history):
                if message.get("role") == "user":
                    user_id = message.get("user_id", "")
                    break

            pending_operation = None
            for message in reversed(history):
                if message.get("role") == "assistant" and "pending_operation" in message:
                    pending_operation = message.get("pending_operation")
                    break

            return ConversationContext(
                user_id=user_id,
                channel_id=record.channel_id,
                thread_ts=record.thread_ts,
                history=history,
                channel_type="im" if record.channel_id.startswith("D") else None,
                pending_operation=pending_operation,
            )

    def save(
        self,
        context: ConversationContext,
    ) -> ConversationContext:
        now = datetime.now(timezone.utc)

        with SessionLocal() as session:
            try:
                query = (
                    session.query(ConversationMemoryModel)
                    .filter(
                        ConversationMemoryModel.channel_id
                        == context.channel_id,
                        ConversationMemoryModel.thread_ts
                        == context.thread_ts,
                    )
                )
                try:
                    if session.bind and session.bind.dialect.name == "postgresql":
                        query = query.with_for_update()
                except Exception:
                    pass

                record = query.first()

                if record is None:
                    record = ConversationMemoryModel(
                        id=str(uuid4()),
                        channel_id=context.channel_id,
                        thread_ts=context.thread_ts,
                        history=context.history,
                        created_at=now,
                        updated_at=now,
                    )

                    session.add(record)

                else:
                    existing_history = record.history or []
                    merged_history = merge_conversation_histories(
                        existing_history,
                        context.history or [],
                    )
                    record.history = merged_history
                    record.updated_at = now

                session.commit()
            except Exception:
                session.rollback()
                raise

        return context

    def get_latest(
        self,
        channel_id: str,
        user_id: str | None = None,
    ) -> ConversationContext | None:
        with SessionLocal() as session:
            records = (
                session.query(ConversationMemoryModel)
                .filter(
                    ConversationMemoryModel.channel_id == channel_id,
                )
                .order_by(
                    ConversationMemoryModel.updated_at.desc(),
                )
                .all()
            )

            for record in records:
                history = record.history or []

                latest_user_id = ""
                for message in reversed(history):
                    if message.get("role") == "user":
                        latest_user_id = message.get("user_id", "")
                        break

                if user_id is not None:
                    if latest_user_id != user_id:
                        continue
                    is_dm = channel_id.startswith("D")
                    if is_dm and any(
                        m.get("role") == "user"
                        and m.get("user_id")
                        and m.get("user_id") != user_id
                        for m in history
                    ):
                        continue

                pending_operation = None
                for message in reversed(history):
                    if message.get("role") == "assistant" and "pending_operation" in message:
                        pending_operation = message.get("pending_operation")
                        break

                return ConversationContext(
                    user_id=latest_user_id,
                    channel_id=record.channel_id,
                    thread_ts=record.thread_ts,
                    history=history,
                    channel_type="im" if record.channel_id.startswith("D") else None,
                    pending_operation=pending_operation,
                )

            return None
