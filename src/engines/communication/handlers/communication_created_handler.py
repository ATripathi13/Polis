"""
Handler for CommunicationCreatedEvent.
"""

from __future__ import annotations

from domain.common.event import DomainEvent

from domain.events import DomainEventHandler

from engines.communication.domain.events import (
    CommunicationCreatedEvent,
)


class CommunicationCreatedHandler(
    DomainEventHandler,
):
    """
    Handles CommunicationCreatedEvent.
    """

    def __init__(self):
        self.handled_events = []

    def handle(
        self,
        event: DomainEvent,
    ) -> None:

        if not isinstance(
            event,
            CommunicationCreatedEvent,
        ):
            return

        self.handled_events.append(event)