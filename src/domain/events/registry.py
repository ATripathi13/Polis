"""
Registry for domain event handlers.
"""

from __future__ import annotations

from collections import defaultdict

from domain.common.event import DomainEvent
from domain.events.handler import DomainEventHandler


class EventRegistry:
    """
    Stores event handler registrations.
    """

    def __init__(self) -> None:
        self._handlers: dict[
            type[DomainEvent],
            list[DomainEventHandler],
        ] = defaultdict(list)

    def register(
        self,
        event_type: type[DomainEvent],
        handler: DomainEventHandler,
    ) -> None:
        """
        Register a handler for an event type.
        """

        self._handlers[event_type].append(handler)

    def get_handlers(
        self,
        event_type: type[DomainEvent],
    ) -> list[DomainEventHandler]:
        """
        Return all handlers for an event type.
        """

        return list(
            self._handlers.get(
                event_type,
                [],
            )
        )