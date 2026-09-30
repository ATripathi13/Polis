"""Reminder service for POLIS."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from domain.reminders import Reminder
from domain.reminders.repositories import ReminderRepository
from zoneinfo import ZoneInfo

class ReminderService:
    """
    Application-facing service for creating and managing reminders.
    """

    def __init__(
        self,
        repository: ReminderRepository,
    ) -> None:
        self._repository = repository

    def create(
        self,
        *,
        target_user_id: str,
        creator_user_id: str,
        task: str,
        channel_id: str,
        source_message_ts: str,
        source_thread_ts: str | None,
        timezone_name: str,
        time_1: str,
        time_2: str,
    ) -> Reminder:

        now = datetime.now(timezone.utc)

        next_reminder_at = self.next_reminder_time(
            now=now,
            timezone_name=timezone_name,
            time_1=time_1,
            time_2=time_2,
        )
        reminder = Reminder.create(
            target_user_id=target_user_id,
            creator_user_id=creator_user_id,
            task=task,
            channel_id=channel_id,
            source_message_ts=source_message_ts,
            source_thread_ts=source_thread_ts,
            active=True,
            next_reminder_at=next_reminder_at,
            last_sent_at=None,
            created_at=now,
            updated_at=now,
        )

        self._repository.save(reminder)

        return reminder

    def find_due(
        self,
        now: datetime | None = None,
    ) -> list[Reminder]:

        if now is None:
            now = datetime.now(timezone.utc)

        return self._repository.find_due(now)

    def stop_for_target(
        self,
        target_user_id: str,
    ) -> int:

        return self._repository.deactivate_for_target(
            target_user_id
        )

    def mark_sent(
        self,
        reminder: Reminder,
        *,
        last_sent_at: datetime,
        next_reminder_at: datetime,
    ) -> None:

        self._repository.mark_sent(
            reminder_id=str(reminder.graph_id),
            last_sent_at=last_sent_at,
            next_reminder_at=next_reminder_at,
        )

    @staticmethod
    def next_reminder_time(
        now: datetime,
        *,
        timezone_name: str,
        time_1: str,
        time_2: str,
    ) -> datetime:
        """
        Return the next configured reminder time in UTC.
        """

        reminder_timezone = ZoneInfo(timezone_name)

        local_now = now.astimezone(reminder_timezone)

        configured_times = [
            time.fromisoformat(time_1),
            time.fromisoformat(time_2),
        ]

        candidates = [
            datetime.combine(
                local_now.date(),
                configured_time,
                tzinfo=reminder_timezone,
            )
            for configured_time in configured_times
        ]

        future_candidates = [
            candidate
            for candidate in candidates
            if candidate > local_now
        ]

        if not future_candidates:
            next_day = local_now.date() + timedelta(days=1)

            future_candidates = [
                datetime.combine(
                    next_day,
                    configured_time,
                    tzinfo=reminder_timezone,
                )
                for configured_time in configured_times
            ]

        return min(future_candidates).astimezone(timezone.utc)