"""
Input DTO for meeting transcript ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MeetingTranscriptInput:
    """
    Source-neutral transcript payload.

    Adapters such as Microsoft Teams translate their
    provider-specific response into this DTO before
    passing it to the application service.
    """

    meeting_id: str
    transcript: str
    source: str
    captured_at: datetime
    participants: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)