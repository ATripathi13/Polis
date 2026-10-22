"""
Application service for managing calendar entries and reminder schedules.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from domain.calendar.entities.calendar_entry import CalendarEntry
from domain.calendar.entities.calendar_reminder_delivery import (
    CalendarReminderDelivery,
)
from domain.calendar.enums import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntryStatus,
    CalendarEntryType,
)
from domain.calendar.exceptions import (
    CalendarEntryNotFoundError,
    InvalidCalendarEntryError,
    InvalidTimeRangeError,
    UnauthorizedCalendarActionError,
)
from domain.calendar.repositories.calendar_repository import CalendarRepository
from domain.calendar.value_objects import (
    CalendarAudience,
    CalendarReminderPolicy,
)
from application.calendar.audience_resolution_service import (
    AudienceResolutionService,
)

logger = logging.getLogger(__name__)


class CalendarService:
    """
    Coordinates calendar operations, audience resolution, validation,
    and reminder delivery scheduling.
    """

    def __init__(
        self,
        repository: CalendarRepository,
        audience_service: AudienceResolutionService,
        reminder_policy: CalendarReminderPolicy | None = None,
        default_timezone: str = "UTC",
    ) -> None:
        self._repository = repository
        self._audience_service = audience_service
        self._reminder_policy = reminder_policy or CalendarReminderPolicy(offset_hours=15)
        self._default_timezone = default_timezone

    @property
    def reminder_policy(self) -> CalendarReminderPolicy:
        return self._reminder_policy

    def create_entry(
        self,
        *,
        title: str,
        description: str = "",
        entry_type: CalendarEntryType | str,
        creator_id: str,
        start_time: datetime,
        end_time: datetime | None = None,
        timezone_name: str | None = None,
        audience_type: CalendarAudienceType | str,
        audience_identifier: str,
        display_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> CalendarEntry:
        """
        Create and persist a calendar entry, resolving its audience and scheduling reminders.
        """
        if isinstance(entry_type, str):
            try:
                entry_type = CalendarEntryType(entry_type.lower())
            except ValueError as err:
                raise InvalidCalendarEntryError(
                    f"Invalid entry type '{entry_type}'. Must be activity, holiday, or announcement."
                ) from err

        tz_name = timezone_name or self._default_timezone

        # 1. Resolve and validate audience
        audience = self._audience_service.resolve(
            audience_type=audience_type,
            audience_identifier=audience_identifier,
            display_name=display_name,
        )

        # 2. Build and validate domain entity
        entry = CalendarEntry.create(
            title=title,
            description=description,
            entry_type=entry_type,
            creator_id=creator_id,
            start_time=start_time,
            end_time=end_time,
            timezone_name=tz_name,
            audience_type=audience.audience_type,
            audience_id=audience.audience_id,
            status=CalendarEntryStatus.SCHEDULED,
            version=1,
            metadata=metadata or {},
        )

        # 3. Persist entry
        saved_entry = self._repository.save_entry(entry)

        # 4. Schedule reminder deliveries
        self._schedule_deliveries_for_entry(saved_entry, audience)

        logger.info(
            "Created calendar entry '%s' (type=%s, start=%s, audience=%s)",
            saved_entry.title,
            saved_entry.entry_type.value,
            saved_entry.start_time.isoformat(),
            saved_entry.audience_type.value,
            extra={
                "operation": "create_calendar_entry",
                "entry_id": saved_entry.entry_id,
                "creator_id": creator_id,
            },
        )
        return saved_entry

    def get_entry(self, entry_id: str) -> CalendarEntry | None:
        return self._repository.find_entry(entry_id)

    def list_entries(
        self,
        *,
        start_range: datetime | None = None,
        end_range: datetime | None = None,
        entry_type: CalendarEntryType | None = None,
        status: CalendarEntryStatus | None = None,
        limit: int = 100,
    ) -> list[CalendarEntry]:
        return self._repository.list_entries(
            start_range=start_range,
            end_range=end_range,
            entry_type=entry_type,
            status=status,
            limit=limit,
        )

    def list_entries_visible_to(
        self,
        user_id: str,
        user_team_ids: list[str] | None = None,
        *,
        start_range: datetime | None = None,
        end_range: datetime | None = None,
        limit: int = 100,
    ) -> list[CalendarEntry]:
        all_entries = self._repository.list_entries(
            start_range=start_range,
            end_range=end_range,
            status=CalendarEntryStatus.SCHEDULED,
            limit=limit * 2,
        )
        visible = [
            e for e in all_entries
            if e.is_visible_to(user_id=user_id, user_team_ids=user_team_ids)
        ]
        return visible[:limit]

    def update_entry(
        self,
        entry_id: str,
        *,
        requester_id: str,
        title: str | None = None,
        description: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        timezone_name: str | None = None,
        audience_type: CalendarAudienceType | str | None = None,
        audience_identifier: str | None = None,
    ) -> CalendarEntry:
        """
        Update an existing entry. Rescheduling start_time recalculates pending reminders.
        """
        entry = self._repository.find_entry(entry_id)
        if entry is None:
            raise CalendarEntryNotFoundError(f"Calendar entry '{entry_id}' not found.")

        # Authorization: creator check
        if entry.creator_id != requester_id:
            raise UnauthorizedCalendarActionError(
                f"User '{requester_id}' is not authorized to modify entry '{entry_id}'."
            )

        if entry.status == CalendarEntryStatus.CANCELLED:
            raise InvalidCalendarEntryError("Cannot modify a cancelled calendar entry.")

        rescheduled = False
        if start_time is not None and start_time != entry.start_time:
            rescheduled = True
            entry.reschedule(
                new_start_time=start_time,
                new_end_time=end_time if end_time is not None else entry.end_time,
                new_timezone=timezone_name,
            )
        else:
            if end_time is not None:
                if end_time < entry.start_time:
                    raise InvalidTimeRangeError("End time cannot precede start time.")
                entry.end_time = end_time
            if timezone_name is not None:
                entry.timezone = timezone_name

        if title is not None:
            if not title.strip():
                raise InvalidCalendarEntryError("Title cannot be empty.")
            entry.title = title.strip()

        if description is not None:
            entry.description = description.strip()

        # Update audience if requested
        audience: CalendarAudience | None = None
        if audience_type is not None or audience_identifier is not None:
            aud_type = audience_type or entry.audience_type
            aud_id = audience_identifier or entry.audience_id
            audience = self._audience_service.resolve(
                audience_type=aud_type,
                audience_identifier=aud_id,
            )
            entry.audience_type = audience.audience_type
            entry.audience_id = audience.audience_id

        entry.updated_at = datetime.now(timezone.utc)
        saved = self._repository.save_entry(entry)

        if rescheduled or audience is not None:
            # Cancel pending deliveries from earlier versions
            cancelled_count = self._repository.cancel_pending_deliveries_for_entry(entry_id)
            logger.info(
                "Rescheduled entry %s: cancelled %d pending deliveries and re-calculating",
                entry_id,
                cancelled_count,
            )
            # Re-resolve audience if not already resolved
            if audience is None:
                audience = self._audience_service.resolve(
                    audience_type=entry.audience_type,
                    audience_identifier=entry.audience_id,
                )
            self._schedule_deliveries_for_entry(saved, audience)

        return saved

    def cancel_entry(
        self,
        entry_id: str,
        *,
        requester_id: str,
    ) -> CalendarEntry:
        """Cancel a calendar entry and all associated pending reminder deliveries."""
        entry = self._repository.find_entry(entry_id)
        if entry is None:
            raise CalendarEntryNotFoundError(f"Calendar entry '{entry_id}' not found.")

        if entry.creator_id != requester_id:
            raise UnauthorizedCalendarActionError(
                f"User '{requester_id}' is not authorized to cancel entry '{entry_id}'."
            )

        entry.cancel()
        saved = self._repository.save_entry(entry)
        cancelled_deliveries = self._repository.cancel_pending_deliveries_for_entry(entry_id)
        logger.info(
            "Cancelled calendar entry %s and %d pending deliveries",
            entry_id,
            cancelled_deliveries,
        )
        return saved

    def get_reminder_status(
        self,
        entry_id: str,
        *,
        requester_id: str,
    ) -> list[CalendarReminderDelivery]:
        """Inspect reminder delivery status for the entry's creator only."""
        entry = self._repository.find_entry(entry_id)
        if entry is None:
            raise CalendarEntryNotFoundError(
                f"Calendar entry '{entry_id}' not found."
            )

        if not requester_id or entry.creator_id != requester_id:
            raise UnauthorizedCalendarActionError(
                "Only the creator can view reminder delivery details."
            )

        return self._repository.find_deliveries_for_entry(entry_id)

    def _schedule_deliveries_for_entry(
        self,
        entry: CalendarEntry,
        audience: CalendarAudience,
    ) -> list[CalendarReminderDelivery]:
        """Create and save delivery obligations based on the entry and resolved audience."""
        due_at = self._reminder_policy.calculate_due_time(entry.start_time)
        deliveries: list[CalendarReminderDelivery] = []

        if audience.audience_type == CalendarAudienceType.INDIVIDUAL:
            d = CalendarReminderDelivery.create(
                entry_id=entry.entry_id,
                recipient_id=audience.audience_id,
                delivery_channel="dm",
                version=entry.version,
                due_at=due_at,
            )
            deliveries.append(self._repository.save_delivery(d))

        elif audience.audience_type == CalendarAudienceType.TEAM:
            # If team has explicit members, send DM to each member
            if audience.resolved_recipients:
                for member_id in audience.resolved_recipients:
                    d = CalendarReminderDelivery.create(
                        entry_id=entry.entry_id,
                        recipient_id=member_id,
                        delivery_channel="dm",
                        version=entry.version,
                        due_at=due_at,
                    )
                    deliveries.append(self._repository.save_delivery(d))
            else:
                # Target team identifier directly
                d = CalendarReminderDelivery.create(
                    entry_id=entry.entry_id,
                    recipient_id=audience.audience_id,
                    delivery_channel="dm",
                    version=entry.version,
                    due_at=due_at,
                )
                deliveries.append(self._repository.save_delivery(d))

        elif audience.audience_type == CalendarAudienceType.ORGANIZATION:
            for recipient in audience.resolved_recipients:
                # If recipient starts with 'C' (Slack public channel) or 'G' (Slack private group), deliver to channel
                ch_type = "channel" if recipient.startswith(("C", "G")) else "dm"
                d = CalendarReminderDelivery.create(
                    entry_id=entry.entry_id,
                    recipient_id=recipient,
                    delivery_channel=ch_type,
                    version=entry.version,
                    due_at=due_at,
                )
                deliveries.append(self._repository.save_delivery(d))

        return deliveries
