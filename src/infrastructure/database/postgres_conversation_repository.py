from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from domain.reasoning.repositories import ConversationRepository
from domain.reasoning.value_objects import ConversationContext

from .connection import SessionLocal
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

            return ConversationContext(
                user_id=user_id,
                channel_id=record.channel_id,
                thread_ts=record.thread_ts,
                history=history,
            )

    def save(
        self,
        context: ConversationContext,
    ) -> ConversationContext:
        now = datetime.now(timezone.utc)

        with SessionLocal() as session:
            record = (
                session.query(ConversationMemoryModel)
                .filter(
                    ConversationMemoryModel.channel_id
                    == context.channel_id,
                    ConversationMemoryModel.thread_ts
                    == context.thread_ts,
                )
                .first()
            )

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
                record.history = context.history
                record.updated_at = now

            session.commit()

        return context