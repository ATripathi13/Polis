"""
Microsoft Teams Application Service.
"""

from __future__ import annotations

import logging
from typing import Any

from application.cognitive import CognitiveEngine

from connectors.microsoft_teams.models import (
    TeamsTranscriptSegment,
)

from connectors.microsoft_teams.normalizers import (
    TeamsNormalizer,
)

from connectors.microsoft_teams.parsers import (
    parse_teams_vtt,
)

from engines.communication.application.commands import (
    IngestCommunicationCommand,
)

from engines.communication.application.services import (
    CommunicationService,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
logger = logging.getLogger(__name__)


class TeamsService:
    """
    Coordinates Teams transcript ingestion and
    POLIS cognitive processing.
    """

    def __init__(
        self,
        normalizer: TeamsNormalizer,
        communication_service: CommunicationService,
        cognitive_engine: CognitiveEngine,
    ) -> None:
        self._normalizer = normalizer
        self._communication_service = communication_service
        self._cognitive_engine = cognitive_engine

    def ingest_transcript(
        self,
        *,
        transcript: str,
        meeting_id: str,
        transcript_id: str,
        meeting_start_time: Any | None = None,
        captured_at: Any | None = None,
        **kwargs: Any,
    ) -> list[CommunicationEvent]:
        """
        Parse, normalize, persist, and cognitively process
        every speaker segment in a Teams transcript.
        """

        segments = parse_teams_vtt(
            transcript,
        )

        saved_events: list[CommunicationEvent] = []

        normalize_kwargs: dict[str, Any] = {}
        if meeting_start_time is not None:
            normalize_kwargs["meeting_start_time"] = meeting_start_time
        if captured_at is not None:
            normalize_kwargs["captured_at"] = captured_at
        normalize_kwargs.update(kwargs)

        for segment in segments:

            communication = self._normalizer.normalize(
                segment=segment,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                **normalize_kwargs,
            )

            command = IngestCommunicationCommand(
                event=communication,
            )

            saved = self._communication_service.process(
                command,
            )

            try:
                self._cognitive_engine.learn(
                    saved,
                )
            except Exception:
                logger.exception(
                    "Teams cognitive processing failed for "
                    "transcript segment %s",
                    communication.source_event_id,
                )

            saved_events.append(saved)

        return saved_events
