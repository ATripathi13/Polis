"""
Input DTO for meeting recording ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MeetingRecordingInput:
    """
    Source-neutral meeting recording payload.

    Adapters such as Microsoft Teams translate their
    provider-specific response into this DTO before
    passing it to the application service.
    """

    meeting_id: str
    content: bytes
    source: str
    captured_at: datetime
    content_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
