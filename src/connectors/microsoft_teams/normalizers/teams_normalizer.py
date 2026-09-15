"""
Microsoft Teams transcript → CommunicationEvent normalizer.
"""

from __future__ import annotations

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

    def normalize(
        self,
        *,
        segment: TeamsTranscriptSegment,
        meeting_id: str,
        transcript_id: str,
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

        content = Content(
            body=segment.text,
            content_type="transcript_segment",
            metadata={
                "meeting_id": meeting_id,
                "transcript_id": transcript_id,
                "speaker": segment.speaker,
                "start_seconds": segment.start.total_seconds(),
                "end_seconds": segment.end.total_seconds(),
            },
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
