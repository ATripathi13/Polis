from domain.common.identifier import Identifier

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.enums import (
    EventSource,
)
from engines.communication.domain.events import (
    CommunicationCreatedEvent,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)


def test_created_event_is_published():

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

    events = communication.pull_domain_events()

    assert len(events) == 1

    domain_event = events[0]

    assert isinstance(
        domain_event,
        CommunicationCreatedEvent,
    )

    assert (
        domain_event.communication_id
        == communication.identifier
    )