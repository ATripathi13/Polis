"""
In-memory repository for testing.
"""

from __future__ import annotations

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.repositories import (
    CommunicationRepository,
)


class InMemoryCommunicationRepository(
    CommunicationRepository,
):
    """
    Simple in-memory repository.
    """

    def __init__(self) -> None:
        self._events: list[CommunicationEvent] = []

    def save(
        self,
        event: CommunicationEvent,
    ) -> CommunicationEvent:
        self._events.append(event)
        return event

    @property
    def events(self) -> list[CommunicationEvent]:
        return self._events