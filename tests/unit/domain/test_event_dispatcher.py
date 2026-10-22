from domain.common.event import DomainEvent

from domain.events import (
    DomainEventHandler,
    EventDispatcher,
    EventRegistry,
)


class SampleEvent(DomainEvent):
    pass


class SampleHandler(DomainEventHandler):

    def __init__(self):
        self.called = False

    def handle(
        self,
        event: DomainEvent,
    ) -> None:
        self.called = True


def test_dispatch():

    registry = EventRegistry()

    handler = SampleHandler()

    registry.register(
        SampleEvent,
        handler,
    )

    dispatcher = EventDispatcher(
        registry,
    )

    dispatcher.dispatch(
        SampleEvent(),
    )

    assert handler.called
