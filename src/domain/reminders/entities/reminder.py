"""Domain entity for POLIS reminders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.common.identifier import Identifier


@dataclass(slots=True)
class Reminder:
    """
    Represents a persistent POLIS reminder for a Slack user.
    """

    identifier: Identifier
    target_user_id: str
    creator_user_id: str
    task: str
    channel_id: str
    source_message_ts: str
    source_thread_ts: str | None
    active: bool
    next_reminder_at: datetime
    last_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def graph_id(self):
        return self.identifier.graph_id

    @classmethod
    def create(
        cls,
        *,
        target_user_id: str,
        creator_user_id: str,
        task: str,
        channel_id: str,
        source_message_ts: str,
        source_thread_ts: str | None,
        active: bool,
        next_reminder_at: datetime,
        last_sent_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
        business_id: str = "",
    ) -> "Reminder":

        return cls(
            identifier=Identifier(
                business_id=business_id,
            ),
            target_user_id=target_user_id,
            creator_user_id=creator_user_id,
            task=task,
            channel_id=channel_id,
            source_message_ts=source_message_ts,
            source_thread_ts=source_thread_ts,
            active=active,
            next_reminder_at=next_reminder_at,
            last_sent_at=last_sent_at,
            created_at=created_at,
            updated_at=updated_at,
        )
