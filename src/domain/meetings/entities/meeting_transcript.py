"""
Domain entity representing the raw transcript of a meeting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from domain.common.entity import Entity
from domain.common.identifier import Identifier


class MeetingTranscript(Entity):
    """
    Raw transcript captured from a meeting.

    This entity intentionally stores source transcript data only.
    AI-extracted knowledge such as decisions, tasks, and facts
    belongs to separate processing layers.
    """

    def __init__(
        self,
        *,
        identifier: Identifier,
        meeting_id: str,
        transcript: str,
        source: str,
        captured_at: datetime,
        participants: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            identifier=identifier,
            metadata=dict(metadata or {}),
        )

        if not meeting_id.strip():
            raise ValueError("meeting_id must not be empty")

        if not transcript.strip():
            raise ValueError("transcript must not be empty")

        if not source.strip():
            raise ValueError("source must not be empty")

        self.meeting_id = meeting_id
        self.transcript = transcript
        self.source = source
        self.captured_at = captured_at
        self.participants = list(participants or [])

    @classmethod
    def create(
        cls,
        *,
        meeting_id: str,
        transcript: str,
        source: str,
        captured_at: datetime,
        participants: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        business_id: str = "",
    ) -> MeetingTranscript:
        return cls(
            identifier=Identifier(
                business_id=business_id,
            ),
            meeting_id=meeting_id,
            transcript=transcript,
            source=source,
            captured_at=captured_at,
            participants=participants,
            metadata=metadata,
        )