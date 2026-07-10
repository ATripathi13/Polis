"""
Base interface for all domain event handlers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.common.event import DomainEvent


class DomainEventHandler(ABC):
    """
    Base interface for every event handler.
    """

    @abstractmethod
    def handle(
        self,
        event: DomainEvent,
    ) -> None:
        """
        Handle a domain event.
        """
        raise NotImplementedError