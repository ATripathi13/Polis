"""
Repository interface for meeting memory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..entities import Meeting


class MeetingRepository(ABC):
    """
    Repository for storing and retrieving meetings.
    """

    @abstractmethod
    def save(
        self,
        meeting: Meeting,
    ) -> None:
        """
        Store a meeting.
        """
        raise NotImplementedError

    @abstractmethod
    def find(
        self,
        identifier: str,
    ) -> Meeting | None:
        """
        Find a meeting by internal identifier.
        """
        raise NotImplementedError

    @abstractmethod
    def find_by_external_id(
        self,
        external_id: str,
    ) -> Meeting | None:
        """
        Find a meeting by its source-system identifier.
        """
        raise NotImplementedError
