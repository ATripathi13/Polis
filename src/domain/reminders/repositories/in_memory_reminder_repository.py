"""
In-memory implementation of ReminderRepository for testing and validation.
"""

from __future__ import annotations

from datetime import datetime
import threading

from domain.reminders.entities import Reminder
from domain.reminders.repositories.reminder_repository import ReminderRepository


class InMemoryReminderRepository(ReminderRepository):
    """In-memory thread-safe implementation of ReminderRepository."""

    def __init__(self) -> None:
        self._reminders: dict[str, Reminder] = {}
        self._lock = threading.Lock()

    def save(
        self,
        reminder: Reminder,
    ) -> None:
        with self._lock:
            self._reminders[str(reminder.graph_id)] = reminder

    def find_due(
        self,
        now: datetime,
    ) -> list[Reminder]:
        with self._lock:
            return sorted(
                [
                    r for r in self._reminders.values()
                    if r.active and r.next_reminder_at <= now
                ],
                key=lambda r: r.next_reminder_at,
            )

    def find_active_for_target(
        self,
        target_user_id: str,
    ) -> list[Reminder]:
        with self._lock:
            return [
                r for r in self._reminders.values()
                if r.target_user_id == target_user_id and r.active
            ]

    def deactivate_for_target(
        self,
        target_user_id: str,
    ) -> int:
        with self._lock:
            count = 0
            for r in self._reminders.values():
                if r.target_user_id == target_user_id and r.active:
                    r.active = False
                    count += 1
            return count

    def mark_sent(
        self,
        reminder_id: str,
        last_sent_at: datetime,
        next_reminder_at: datetime,
    ) -> None:
        with self._lock:
            if reminder_id in self._reminders:
                r = self._reminders[reminder_id]
                r.last_sent_at = last_sent_at
                r.next_reminder_at = next_reminder_at

    def find_by_id(
        self,
        reminder_id: str,
    ) -> Reminder | None:
        with self._lock:
            return self._reminders.get(reminder_id)

    def list_all(self) -> list[Reminder]:
        with self._lock:
            return list(self._reminders.values())
