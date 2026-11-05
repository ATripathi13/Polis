from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from engines.communication.domain.aggregates import CommunicationEvent


class CommunicationRepository(ABC):

    @abstractmethod
    def save(
        self,
        event: CommunicationEvent,
    ) -> CommunicationEvent:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 20,
        actor_id: str | None = None,
        exclude_questions: bool = False,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[CommunicationEvent]:
        raise NotImplementedError

    @abstractmethod
    def get_person_recent_activity(
        self,
        *,
        actor_ids: list[str] | str,
        actor_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        include_mentions: bool = True,
        include_parent_context: bool = True,
    ) -> list[CommunicationEvent]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_events(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 500,
        include_parent_context: bool = True,
    ) -> list[CommunicationEvent]:
        raise NotImplementedError
