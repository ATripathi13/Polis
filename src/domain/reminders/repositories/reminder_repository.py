"""Repository interface for POLIS reminders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..entities import Reminder


class ReminderRepository(ABC):
    """
    Repository interface for persistent POLIS reminders.
    """

    @abstractmethod
    def save(
        self,
        reminder: Reminder,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_due(
        self,
        now: datetime,
    ) -> list[Reminder]:
        raise NotImplementedError

    @abstractmethod
    def find_active_for_target(
        self,
        target_user_id: str,
    ) -> list[Reminder]:
        raise NotImplementedError

    @abstractmethod
    def deactivate_for_target(
        self,
        target_user_id: str,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def mark_sent(
        self,
        reminder_id: str,
        last_sent_at: datetime,
        next_reminder_at: datetime,
    ) -> None:
        raise NotImplementedError
