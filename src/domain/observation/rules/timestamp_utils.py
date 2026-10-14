"""Timestamp helpers for observation extraction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def resolve_occurred_at(communication: Any) -> datetime | None:
    """Resolve source event time, falling back to ingestion time."""
    raw_timestamp = communication.content.metadata.get("source_timestamp")

    if raw_timestamp is not None:
        try:
            timestamp = datetime.fromtimestamp(
                float(raw_timestamp),
                tz=timezone.utc,
            )
            return timestamp
        except (TypeError, ValueError, OverflowError, OSError):
            pass

    return getattr(communication, "created_at", None)
