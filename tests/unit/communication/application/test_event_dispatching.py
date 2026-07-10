from domain.common.identifier import Identifier

from domain.events import (
    EventDispatcher,
    EventRegistry,
)

from engines.communication.application.commands import (
    IngestCommunicationCommand,
)
from engines.communication.application.services import (
    CommunicationService,
)
from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from engines.communication.handlers import (
    CommunicationCreatedHandler,
)
from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)
from engines.communication.domain.events import (
    CommunicationCreatedEvent,
)


def test_process_dispatches_events():

    repository = InMemoryCommunicationRepository()

    registry = EventRegistry()

    handler = CommunicationCreatedHandler()

    registry.register(
        CommunicationCreatedEvent,
        handler,
    )

    dispatcher = EventDispatcher(
        registry,
    )

    service = CommunicationService(
        repository=repository,
        dispatcher=dispatcher,
    )

    communication = CommunicationEvent.create(
        correlation_id=Identifier(
            business_id="THREAD-001",
        ),
        source=EventSource.SLACK,
        source_event_id="1712345678",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="USER-001",
            ),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="CHANNEL-001",
            ),
            name="general",
            channel_type="public",
        ),
        content=Content(
            body="Hello Polis!",
        ),
    )

    command = IngestCommunicationCommand(
        event=communication,
    )

    service.process(command)

    assert len(handler.handled_events) == 1