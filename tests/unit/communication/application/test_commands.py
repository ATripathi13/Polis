from domain.common.identifier import Identifier

from engines.communication.application.commands import (
    IngestCommunicationCommand,
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


def test_create_ingest_command():

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

    command = IngestCommunicationCommand(
        event=event,
    )

    assert command.event == event