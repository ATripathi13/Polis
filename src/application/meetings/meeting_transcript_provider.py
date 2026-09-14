"""
Provider interface for meeting transcript retrieval.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from application.meetings.meeting_transcript_input import (
    MeetingTranscriptInput,
)


class MeetingTranscriptProvider(ABC):
    """
    Source adapter interface for retrieving meeting transcripts.

    Provider-specific APIs such as Microsoft Graph should implement
    this interface and return the source-neutral input DTO.
    """

    @abstractmethod
    def get_transcript(
        self,
        meeting_id: str,
    ) -> MeetingTranscriptInput | None:
        raise NotImplementedError