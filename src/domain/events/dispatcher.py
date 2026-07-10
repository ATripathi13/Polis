"""
Dispatches domain events to registered handlers.
"""

from __future__ import annotations

from domain.common.event import DomainEvent

from domain.events.registry import EventRegistry


class EventDispatcher:
    """
    Dispatches domain events.
    """

    def __init__(
        self,
        registry: EventRegistry,
    ) -> None:
        self._registry = registry

    def dispatch(
        self,
        event: DomainEvent,
    ) -> None:
        """
        Dispatch one event.
        """

        handlers = self._registry.get_handlers(
            type(event),
        )

        for handler in handlers:
            handler.handle(event)