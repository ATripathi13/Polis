"""
Microsoft Teams transcript → CommunicationEvent normalizer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from domain.common.identifier import Identifier

from connectors.microsoft_teams.models import (
    TeamsTranscriptSegment,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from engines.communication.domain.enums import (
    EventSource,
)

from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)


class TeamsNormalizer:
    """
    Converts Teams transcript segments into
    CommunicationEvent aggregates.
    """

    @staticmethod
    def _parse_to_utc_datetime(value: Any) -> datetime | None:
        """
        Parse a datetime, ISO string, or numeric epoch timestamp into a timezone-aware UTC datetime.
        Returns None if value cannot be parsed or is None.
        """
        if value is None:
            return None

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)

        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError):
                return None

        if isinstance(value, str):
            val_str = value.strip()
            if not val_str:
                return None

            if "-" in val_str or ":" in val_str or "T" in val_str:
                try:
                    dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        return dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(timezone.utc)
                except (TypeError, ValueError):
                    pass

            try:
                return datetime.fromtimestamp(float(val_str), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError):
                pass

            try:
                dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (TypeError, ValueError):
                return None

        return None

    def normalize(
        self,
        *,
        segment: TeamsTranscriptSegment,
        meeting_id: str,
        transcript_id: str,
        meeting_start_time: datetime | str | None = None,
        captured_at: datetime | str | None = None,
        source_timestamp: str | float | int | datetime | None = None,
        metadata: dict[str, Any] | None = None,
        **extra_kwargs: Any,
    ) -> CommunicationEvent:
        """
        Convert one Teams transcript segment into
        a CommunicationEvent.
        """

        source_event_id = (
            f"{transcript_id}:"
            f"{segment.start.total_seconds():.3f}:"
            f"{segment.end.total_seconds():.3f}:"
            f"{segment.speaker}"
        )

        actor = Actor(
            identity=CommunicationIdentity(
                internal_id=segment.speaker,
                external_ids={
                    "microsoft_teams": segment.speaker,
                },
            ),
            display_name=segment.speaker,
        )

        channel = Channel(
            identity=CommunicationIdentity(
                internal_id=meeting_id,
                external_ids={
                    "microsoft_teams": meeting_id,
                },
            ),
            name=meeting_id,
            channel_type="meeting",
            metadata={
                "meeting_id": meeting_id,
                "transcript_id": transcript_id,
            },
        )

        content_metadata: dict[str, Any] = {}
        if metadata:
            content_metadata.update(metadata)

        content_metadata.update(
            {
                "meeting_id": meeting_id,
                "transcript_id": transcript_id,
                "speaker": segment.speaker,
                "start_seconds": segment.start.total_seconds(),
                "end_seconds": segment.end.total_seconds(),
            }
        )

        # Resolve absolute occurrence time when reliable timing info is available
        source_ts_candidate = source_timestamp
        if source_ts_candidate is None and metadata:
            source_ts_candidate = metadata.get("source_timestamp")
        if source_ts_candidate is None and extra_kwargs:
            source_ts_candidate = extra_kwargs.get("source_timestamp")

        if source_ts_candidate is not None:
            if isinstance(source_ts_candidate, (int, float)):
                content_metadata["source_timestamp"] = f"{float(source_ts_candidate):.6f}"
            elif isinstance(source_ts_candidate, str):
                parsed = self._parse_to_utc_datetime(source_ts_candidate)
                if parsed is not None:
                    try:
                        float(source_ts_candidate)
                        content_metadata["source_timestamp"] = source_ts_candidate
                    except ValueError:
                        content_metadata["source_timestamp"] = f"{parsed.timestamp():.6f}"
                else:
                    content_metadata["source_timestamp"] = source_ts_candidate
            elif isinstance(source_ts_candidate, datetime):
                parsed = self._parse_to_utc_datetime(source_ts_candidate)
                if parsed is not None:
                    content_metadata["source_timestamp"] = f"{parsed.timestamp():.6f}"
        else:
            # 1. Check meeting start time
            start_candidate = meeting_start_time
            if start_candidate is None and metadata:
                start_candidate = (
                    metadata.get("meeting_started_at")
                    or metadata.get("meeting_start_time")
                    or metadata.get("startDateTime")
                )
            if start_candidate is None and extra_kwargs:
                start_candidate = (
                    extra_kwargs.get("meeting_started_at")
                    or extra_kwargs.get("meeting_start_time")
                    or extra_kwargs.get("startDateTime")
                )

            base_dt = self._parse_to_utc_datetime(start_candidate)

            # 2. Check capture time if meeting start time is not available
            if base_dt is None:
                capture_candidate = captured_at
                if capture_candidate is None and metadata:
                    capture_candidate = metadata.get("captured_at") or metadata.get("createdDateTime")
                if capture_candidate is None and extra_kwargs:
                    capture_candidate = extra_kwargs.get("captured_at") or extra_kwargs.get("createdDateTime")
                base_dt = self._parse_to_utc_datetime(capture_candidate)

            if base_dt is not None:
                offset = getattr(segment, "start", None)
                if isinstance(offset, timedelta):
                    computed_occurred_at = base_dt + offset
                elif isinstance(offset, (int, float)):
                    computed_occurred_at = base_dt + timedelta(seconds=float(offset))
                else:
                    computed_occurred_at = base_dt

                content_metadata["source_timestamp"] = f"{computed_occurred_at.timestamp():.6f}"

        content = Content(
            body=segment.text,
            content_type="transcript_segment",
            metadata=content_metadata,
        )

        return CommunicationEvent.create(
            correlation_id=Identifier(
                business_id=meeting_id,
            ),
            source=EventSource.MICROSOFT_TEAMS,
            source_event_id=source_event_id,
            actor=actor,
            channel=channel,
            content=content,
        )
