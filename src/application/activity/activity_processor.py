from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from domain.activity import (
    ActivitySource,
    ActivityType,
    PersonPreferenceRepository,
    WorkdaySessionRepository,
)
from engines.slack.dto import SlackMessage

from .activity_detector import ActivityDetector
from .activity_service import ActivityService


class ActivityProcessor:
    """
    Converts explicit Slack activity signals into
    persisted activity events and coordinates workday session lifecycles.
    """

    def __init__(
        self,
        detector: ActivityDetector,
        activity_service: ActivityService,
        workday_session_repository: WorkdaySessionRepository | None = None,
        person_preference_repository: PersonPreferenceRepository | None = None,
        default_timezone: str | None = None,
        identity_service: Any | None = None,
    ) -> None:
        self._detector = detector
        self._activity_service = activity_service

        if (
            workday_session_repository is not None
            and getattr(self._activity_service, "_workday_session_repository", None) is None
        ):
            self._activity_service._workday_session_repository = workday_session_repository

        if (
            person_preference_repository is not None
            and getattr(self._activity_service, "_person_preference_repository", None) is None
        ):
            self._activity_service._person_preference_repository = person_preference_repository

        if (
            default_timezone is not None
            and getattr(self._activity_service, "_default_timezone", None) is None
        ):
            self._activity_service._default_timezone = default_timezone

        if (
            identity_service is not None
            and getattr(self._activity_service, "_identity_service", None) is None
        ):
            self._activity_service._identity_service = identity_service

    def process(
        self,
        message: SlackMessage,
    ) -> None:
        detected = self._detector.detect(
            message.text,
        )

        if detected is None:
            return

        occurred_at = self._message_timestamp(
            message.ts or message.event_ts,
        )

        person_name = (
            message.user_name.strip()
            if message.user_name and message.user_name.strip()
            else message.user
        )

        source_event_id = message.event_ts or message.ts

        self._activity_service.record(
            person_id=message.user,
            person_name=person_name,
            activity_type=detected.activity_type,
            occurred_at=occurred_at,
            source=ActivitySource.SLACK,
            source_event_id=source_event_id,
            break_type=detected.break_type,
            note=detected.note,
        )

        if detected.activity_type == ActivityType.WORK_START:
            self._activity_service.start_workday_session(
                person_id=message.user,
                person_name=person_name,
                occurred_at=occurred_at,
                source_event_id=source_event_id,
            )
        elif detected.activity_type == ActivityType.WORK_END:
            self._activity_service.sign_off_workday_session(
                person_id=message.user,
                occurred_at=occurred_at,
                source_event_id=source_event_id,
            )

    @staticmethod
    def _message_timestamp(
        timestamp: str | float | int | datetime | None,
    ) -> datetime:
        if timestamp is None:
            return datetime.now(timezone.utc)
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                return timestamp.replace(tzinfo=timezone.utc)
            return timestamp.astimezone(timezone.utc)
        try:
            val = float(str(timestamp).strip())
            return datetime.fromtimestamp(
                val,
                tz=timezone.utc,
            )
        except (ValueError, TypeError, OverflowError, OSError):
            return datetime.now(timezone.utc)

    process_message = process