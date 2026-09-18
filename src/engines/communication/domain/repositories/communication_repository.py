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