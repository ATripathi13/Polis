"""
Background worker for reliable delivery of calendar reminders.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

from domain.calendar.entities.calendar_entry import CalendarEntry
from domain.calendar.entities.calendar_reminder_delivery import (
    CalendarReminderDelivery,
)
from domain.calendar.enums import CalendarDeliveryStatus
from domain.calendar.repositories.calendar_repository import CalendarRepository

logger = logging.getLogger(__name__)


class CalendarReminderWorker:
    """
    Background worker that queries due calendar reminders and delivers
    them through Slack with idempotency and atomic locking.
    """

    def __init__(
        self,
        repository: CalendarRepository,
        slack_client: Any,
        poll_interval_seconds: int = 30,
        max_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._slack_client = slack_client
        self._poll_interval = max(5, poll_interval_seconds)
        self._max_attempts = max_attempts
        self._running = False
        self._thread: threading.Thread | None = None

    def poll_and_deliver(self, now: datetime | None = None) -> int:
        """
        Execute one delivery iteration.
        Returns the number of successfully sent reminders.
        """
        current_time = now or datetime.now(timezone.utc)
        due_deliveries = self._repository.find_due_deliveries(
            now=current_time,
            limit=50,
        )

        sent_count = 0

        for delivery in due_deliveries:
            # 1. Attempt atomic claim to avoid race conditions across multiple workers
            claimed = self._repository.claim_due_delivery(
                delivery_id=delivery.delivery_id,
                claim_time=current_time,
            )
            if not claimed:
                # Claimed by another concurrent worker instance
                continue

            entry = self._repository.find_entry(delivery.entry_id)
            if entry is None or entry.status.value == "cancelled":
                # Entry was cancelled or removed, mark delivery as cancelled
                self._repository.cancel_pending_deliveries_for_entry(delivery.entry_id)
                continue

            # 2. Format notification
            message_text = self._format_reminder_text(entry)

            # 3. Deliver via Slack
            try:
                if delivery.delivery_channel == "dm":
                    dm_channel = self._slack_client.open_dm(delivery.recipient_id)
                    self._slack_client.post_message(
                        channel=dm_channel,
                        text=message_text,
                    )
                else:
                    self._slack_client.post_message(
                        channel=delivery.recipient_id,
                        text=message_text,
                    )

                sent_at = datetime.now(timezone.utc)
                self._repository.mark_delivery_sent(
                    delivery_id=delivery.delivery_id,
                    sent_at=sent_at,
                )
                sent_count += 1
                logger.info(
                    "Sent calendar reminder for entry '%s' to recipient '%s'",
                    entry.title,
                    delivery.recipient_id,
                    extra={
                        "operation": "calendar_reminder_delivered",
                        "entry_id": entry.entry_id,
                        "recipient_id": delivery.recipient_id,
                        "idempotency_key": delivery.idempotency_key,
                    },
                )

            except Exception as err:
                logger.warning(
                    "Failed to deliver calendar reminder for entry '%s' to '%s': %s",
                    entry.title,
                    delivery.recipient_id,
                    str(err),
                    exc_info=True,
                    extra={
                        "operation": "calendar_reminder_failure",
                        "entry_id": entry.entry_id,
                        "recipient_id": delivery.recipient_id,
                    },
                )
                self._repository.mark_delivery_failed(
                    delivery_id=delivery.delivery_id,
                    error_message=str(err),
                    attempt_time=datetime.now(timezone.utc),
                    max_attempts=self._max_attempts,
                )

        return sent_count

    def _format_reminder_text(self, entry: CalendarEntry) -> str:
        """Format friendly Slack message with timezone-converted scheduled time."""
        try:
            tz = ZoneInfo(entry.timezone)
            local_start = entry.start_time.astimezone(tz)
            formatted_time = local_start.strftime("%Y-%m-%d %I:%M %p")
        except Exception:
            formatted_time = entry.start_time.strftime("%Y-%m-%d %H:%M UTC")

        type_label = entry.entry_type.value.capitalize()
        lines = [
            f"📅 *POLIS Calendar Reminder* (Scheduled in 15 hours)",
            f"*Type:* {type_label}",
            f"*Title:* {entry.title}",
            f"*Scheduled Start:* {formatted_time} ({entry.timezone})",
        ]
        if entry.end_time is not None:
            try:
                tz = ZoneInfo(entry.timezone)
                local_end = entry.end_time.astimezone(tz)
                lines.append(f"*Scheduled End:* {local_end.strftime('%Y-%m-%d %I:%M %p')} ({entry.timezone})")
            except Exception:
                pass

        if entry.description:
            lines.append(f"*Details:* {entry.description}")

        return "\n".join(lines)

    def _worker_loop(self) -> None:
        while self._running:
            try:
                self.poll_and_deliver()
            except Exception:
                logger.exception("Unexpected error in calendar reminder worker iteration")

            time.sleep(self._poll_interval)

    def start(self) -> None:
        """Start the background reminder worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="polis-calendar-reminder-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Calendar reminder worker thread started (poll_interval=%ds)",
            self._poll_interval,
            extra={"operation": "start_calendar_worker"},
        )

    def stop(self) -> None:
        """Stop the background reminder worker thread."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Calendar reminder worker stopped", extra={"operation": "stop_calendar_worker"})
