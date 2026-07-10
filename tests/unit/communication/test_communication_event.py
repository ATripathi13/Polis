from domain.common.identifier import Identifier

from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import (
    EventSource,
    ProcessingStatus,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)

from domain.common.identifier import Identifier

from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import (
    EventSource,
    ProcessingStatus,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from engines.communication.domain.value_objects import (
    Mention,
)

def create_test_event() -> CommunicationEvent:
    """
    Creates a valid CommunicationEvent for testing.
    """

    actor = Actor(
        identity=CommunicationIdentity(
            internal_id="USER-001",
        ),
        display_name="John Doe",
    )

    channel = Channel(
        identity=CommunicationIdentity(
            internal_id="CHANNEL-001",
        ),
        name="general",
        channel_type="public",
    )

    content = Content(
        body="Hello Polis!",
    )

    return CommunicationEvent.create(
        correlation_id=Identifier(
            business_id="THREAD-001",
        ),
        source=EventSource.SLACK,
        source_event_id="1712345678.123456",
        actor=actor,
        channel=channel,
        content=content,
    )
def test_create_communication_event():

    # Arrange

    identity = CommunicationIdentity(
        internal_id="USER-001",
    )

    actor = Actor(
        identity=identity,
        display_name="John Doe",
    )

    channel = Channel(
        identity=CommunicationIdentity(
            internal_id="CHANNEL-001",
        ),
        name="general",
        channel_type="public",
    )

    content = Content(
        body="Hello Polis!",
    )

    # Act

    event = CommunicationEvent(
        correlation_id=Identifier(
            business_id="THREAD-001",
        ),
        source=EventSource.SLACK,
        source_event_id="123456789",
        actor=actor,
        channel=channel,
        content=content,
    )

    # Assert

    assert event.identifier is not None
    assert event.correlation_id.business_id == "THREAD-001"

    assert event.source == EventSource.SLACK
    assert event.status == ProcessingStatus.RECEIVED

    assert event.actor.display_name == "John Doe"
    assert event.channel.name == "general"
    assert event.content.body == "Hello Polis!"

    assert event.attachments == []
    assert event.references == []
    event.validate()

import pytest

from domain.common.identifier import Identifier

from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import (
    EventSource,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
)


def test_validate_requires_content():

    identity = CommunicationIdentity(
        internal_id="USER-001",
    )

    actor = Actor(
        identity=identity,
        display_name="John Doe",
    )

    channel = Channel(
        identity=CommunicationIdentity(
            internal_id="CHANNEL-001",
        ),
        name="general",
        channel_type="public",
    )

    event = CommunicationEvent(
        correlation_id=Identifier(
            business_id="THREAD-001",
        ),
        source=EventSource.SLACK,
        source_event_id="123456",
        actor=actor,
        channel=channel,
        content=None,   # type: ignore
    )

    with pytest.raises(ValueError):
        event.validate()

def test_mark_normalized():

    event = create_test_event()

    event.mark_normalized()

    assert event.status == ProcessingStatus.NORMALIZED

def test_invalid_transition():

    event = create_test_event()

    with pytest.raises(ValueError):
        event.mark_persisted()

def test_is_addressed_to():

    event = create_test_event()

    event.mentions.append(
        Mention(
            identity=CommunicationIdentity(
                internal_id="POLIS",
            ),
            display_name="Polis",
        )
    )

    assert event.is_addressed_to("POLIS")

    assert not event.is_addressed_to("OTHER")

def test_detect_question_mark():

    event = create_test_event()

    event.content = Content(
        body="What database do we use?",
    )

    assert event.is_question()

def test_detect_question_without_question_mark():

    event = create_test_event()

    event.content = Content(
        body="Summarize today's decisions",
    )

    assert event.is_question()

def test_detect_normal_statement():

    event = create_test_event()

    event.content = Content(
        body="We migrated to PostgreSQL.",
    )

    assert not event.is_question()