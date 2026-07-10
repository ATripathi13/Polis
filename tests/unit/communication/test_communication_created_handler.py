from domain.common.identifier import Identifier

from domain.events import (
    EventDispatcher,
    EventRegistry,
)

from engines.communication.domain.events import (
    CommunicationCreatedEvent,
)

from engines.communication.handlers import (
    CommunicationCreatedHandler,
)


def test_handler_receives_event():

    registry = EventRegistry()

    handler = CommunicationCreatedHandler()

    registry.register(
        CommunicationCreatedEvent,
        handler,
    )

    dispatcher = EventDispatcher(
        registry,
    )

    event = CommunicationCreatedEvent(
        communication_id=Identifier(),
    )

    dispatcher.dispatch(event)

    assert len(handler.handled_events) == 1

    assert (
        handler.handled_events[0]
        == event
    )