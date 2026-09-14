"""
Repository interface for meeting transcripts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..entities import MeetingTranscript


class MeetingTranscriptRepository(ABC):
    """
    Repository interface for meeting transcript memory.
    """

    @abstractmethod
    def save(
        self,
        transcript: MeetingTranscript,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find(
        self,
        identifier: str,
    ) -> MeetingTranscript | None:
        raise NotImplementedError

    @abstractmethod
    def find_by_meeting_id(
        self,
        meeting_id: str,
    ) -> list[MeetingTranscript]:
        raise NotImplementedError
