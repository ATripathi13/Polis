from domain.common.event import DomainEvent

from domain.events import (
    DomainEventHandler,
    EventDispatcher,
    EventRegistry,
)


class TestEvent(DomainEvent):
    pass


class TestHandler(DomainEventHandler):

    def __init__(self):
        self.called = False

    def handle(
        self,
        event: DomainEvent,
    ) -> None:
        self.called = True


def test_dispatch():

    registry = EventRegistry()

    handler = TestHandler()

    registry.register(
        TestEvent,
        handler,
    )

    dispatcher = EventDispatcher(
        registry,
    )

    dispatcher.dispatch(
        TestEvent(),
    )

    assert handler.called