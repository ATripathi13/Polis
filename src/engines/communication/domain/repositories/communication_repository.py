from __future__ import annotations

from abc import ABC, abstractmethod

from engines.communication.domain.aggregates import CommunicationEvent


class CommunicationRepository(ABC):

    @abstractmethod
    def save(
        self,
        event: CommunicationEvent,
    ) -> CommunicationEvent:
        raise NotImplementedError