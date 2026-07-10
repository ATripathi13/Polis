from engines.communication.application.services import (
    CommunicationService,
)

from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)

from domain.common.identifier import Identifier

from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import (
    EventSource,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from domain.events import (
    EventDispatcher,
    EventRegistry,
)

def test_create_service():

    repository = InMemoryCommunicationRepository()

    registry = EventRegistry()

    dispatcher = EventDispatcher(
    registry,
    )

    service = CommunicationService(
    repository=repository,
    dispatcher=dispatcher,
    )
    assert service is not None


def test_process_event():

    repository = InMemoryCommunicationRepository()
    
    registry = EventRegistry()

    dispatcher = EventDispatcher(
        registry,
    )

    service = CommunicationService(
        repository=repository,
        dispatcher=dispatcher,
    )

    event = CommunicationEvent.create(
        correlation_id=Identifier(
            business_id="THREAD-001",
        ),
        source=EventSource.SLACK,
        source_event_id="1712345678.123456",
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

    from engines.communication.application.commands import (
        IngestCommunicationCommand,
    )

    command = IngestCommunicationCommand(
        event=event,
    )

    saved = service.process(command)

    assert saved == event
    assert len(repository.events) == 1
    assert repository.events[0] == event