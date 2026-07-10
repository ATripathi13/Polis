from domain.common.identifier import Identifier

from domain.reasoning import (
    ReasoningAction,
    ReasoningContext,
)

from domain.reasoning.policies import (
    MentionPolicy,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from engines.communication.domain.enums import (
    EventSource,
)

from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
    Mention,
)


def create_event() -> CommunicationEvent:

    return CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="USER1",
            ),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="CHANNEL1",
            ),
            name="general",
            channel_type="public",
        ),
        content=Content(
            body="Hello",
        ),
    )


def test_policy_ignores_normal_messages():

    policy = MentionPolicy()

    context = ReasoningContext(
        communication=create_event(),
    )

    assert policy.evaluate(context) is None


def test_policy_detects_mentions():

    event = create_event()

    event.mentions.append(
        Mention(
            identity=CommunicationIdentity(
                internal_id="POLIS",
            ),
            display_name="Polis",
        )
    )

    context = ReasoningContext(
        communication=event,
    )

    policy = MentionPolicy()

    decision = policy.evaluate(context)

    assert decision is not None

    assert decision.action == ReasoningAction.REPLY