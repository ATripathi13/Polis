from domain.common.event import DomainEvent
from domain.events import (
    DomainEventHandler,
    EventRegistry,
)


class TestEvent(DomainEvent):
    pass


class TestHandler(DomainEventHandler):

    def handle(
        self,
        event: DomainEvent,
    ) -> None:
        pass


def test_register_handler():

    registry = EventRegistry()

    handler = TestHandler()

    registry.register(
        TestEvent,
        handler,
    )

    handlers = registry.get_handlers(
        TestEvent,
    )

    assert len(handlers) == 1

    assert handlers[0] == handler