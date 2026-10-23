from domain.common.event import DomainEvent
from domain.events import (
    DomainEventHandler,
    EventRegistry,
)


class SampleEvent(DomainEvent):
    pass


class SampleHandler(DomainEventHandler):

    def handle(
        self,
        event: DomainEvent,
    ) -> None:
        pass


def test_register_handler():

    registry = EventRegistry()

    handler = SampleHandler()

    registry.register(
        SampleEvent,
        handler,
    )

    handlers = registry.get_handlers(
        SampleEvent,
    )

    assert len(handlers) == 1

    assert handlers[0] == handler
