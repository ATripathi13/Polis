"""
Provider interface for meeting recording retrieval.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from application.meetings.meeting_recording_input import (
    MeetingRecordingInput,
)


class MeetingRecordingProvider(ABC):
    """
    Source adapter interface for retrieving meeting recordings.

    Provider-specific APIs such as Microsoft Graph should implement
    this interface and return the source-neutral input DTO.
    """

    @abstractmethod
    def get_recording_by_notification(
        self,
        *,
        user_id: str,
        online_meeting_id: str,
        recording_id: str,
    ) -> MeetingRecordingInput | None:
        raise NotImplementedError
