from __future__ import annotations

from datetime import datetime, timezone

from domain.activity import (
    ActivityService,
    ActivitySource,
)

from engines.slack.dto import SlackMessage

from .activity_detector import ActivityDetector


class ActivityProcessor:
    """
    Converts explicit Slack activity signals into
    persisted activity events.
    """

    def __init__(
        self,
        detector: ActivityDetector,
        activity_service: ActivityService,
    ) -> None:
        self._detector = detector
        self._activity_service = activity_service

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
            message.ts,
        )

        self._activity_service.record(
            person_id=message.user,
            person_name=message.user,
            activity_type=detected.activity_type,
            occurred_at=occurred_at,
            source=ActivitySource.SLACK,
            source_event_id=message.event_ts,
            break_type=detected.break_type,
            note=detected.note,
        )

    @staticmethod
    def _message_timestamp(
        timestamp: str,
    ) -> datetime:

        return datetime.fromtimestamp(
            float(timestamp),
            tz=timezone.utc,
        )