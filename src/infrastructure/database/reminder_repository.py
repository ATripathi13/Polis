"""PostgreSQL repository for POLIS reminders."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from domain.reminders import Reminder
from domain.reminders.repositories import ReminderRepository
from domain.common.identifier import Identifier

from .connection import SessionLocal
from .models import ReminderModel


class PostgreSQLReminderRepository(ReminderRepository):
    """
    PostgreSQL implementation of ReminderRepository.
    """

    def save(
        self,
        reminder: Reminder,
    ) -> None:

        with SessionLocal() as session:

            record = (
                session.query(ReminderModel)
                .filter(
                    ReminderModel.id
                    == str(reminder.graph_id)
                )
                .first()
            )

            if record is None:

                record = ReminderModel(
                    id=str(reminder.graph_id),
                    target_user_id=reminder.target_user_id,
                    creator_user_id=reminder.creator_user_id,
                    task=reminder.task,
                    channel_id=reminder.channel_id,
                    source_message_ts=reminder.source_message_ts,
                    source_thread_ts=reminder.source_thread_ts,
                    active=reminder.active,
                    next_reminder_at=reminder.next_reminder_at,
                    last_sent_at=reminder.last_sent_at,
                    created_at=reminder.created_at,
                    updated_at=reminder.updated_at,
                )

                session.add(record)

            else:

                record.target_user_id = reminder.target_user_id
                record.creator_user_id = reminder.creator_user_id
                record.task = reminder.task
                record.channel_id = reminder.channel_id
                record.source_message_ts = reminder.source_message_ts
                record.source_thread_ts = reminder.source_thread_ts
                record.active = reminder.active
                record.next_reminder_at = reminder.next_reminder_at
                record.last_sent_at = reminder.last_sent_at
                record.updated_at = reminder.updated_at

            session.commit()

    def find_due(
        self,
        now: datetime,
    ) -> list[Reminder]:

        with SessionLocal() as session:

            records = (
                session.query(ReminderModel)
                .filter(
                    ReminderModel.active.is_(True),
                    ReminderModel.next_reminder_at <= now,
                )
                .order_by(
                    ReminderModel.next_reminder_at.asc()
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

    def find_active_for_target(
        self,
        target_user_id: str,
    ) -> list[Reminder]:

        with SessionLocal() as session:

            records = (
                session.query(ReminderModel)
                .filter(
                    ReminderModel.target_user_id
                    == target_user_id,
                    ReminderModel.active.is_(True),
                )
                .order_by(
                    ReminderModel.created_at.asc()
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

    def deactivate_for_target(
        self,
        target_user_id: str,
    ) -> int:

        now = datetime.now(timezone.utc)

        with SessionLocal() as session:

            records = (
                session.query(ReminderModel)
                .filter(
                    ReminderModel.target_user_id
                    == target_user_id,
                    ReminderModel.active.is_(True),
                )
                .all()
            )

            for record in records:
                record.active = False
                record.updated_at = now

            session.commit()

            return len(records)

    def mark_sent(
        self,
        reminder_id: str,
        last_sent_at: datetime,
        next_reminder_at: datetime,
    ) -> None:

        now = datetime.now(timezone.utc)

        with SessionLocal() as session:

            record = session.get(
                ReminderModel,
                reminder_id,
            )

            if record is None:
                return

            record.last_sent_at = last_sent_at
            record.next_reminder_at = next_reminder_at
            record.updated_at = now

            session.commit()

    @staticmethod
    def _to_domain(
        record: ReminderModel,
    ) -> Reminder:

        return Reminder(
            identifier=Identifier(
                graph_id=UUID(record.id),
            ),
            target_user_id=record.target_user_id,
            creator_user_id=record.creator_user_id,
            task=record.task,
            channel_id=record.channel_id,
            source_message_ts=record.source_message_ts,
            source_thread_ts=record.source_thread_ts,
            active=record.active,
            next_reminder_at=record.next_reminder_at,
            last_sent_at=record.last_sent_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
