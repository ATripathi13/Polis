from domain.common.identifier import Identifier

from domain.reasoning import (
    RuleBasedReasoningService,
    ReasoningAction,
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
)

from engines.communication.domain.value_objects import (
    Mention,
)

from domain.reasoning import (
        ReasoningPolicyRegistry,
    )

from domain.reasoning.policies import (
    MentionPolicy,
)

def test_reply_when_addressed_to_polis():

    event = create_event(
        "Hello",
    )

    event.mentions.append(
        Mention(
            identity=CommunicationIdentity(
                internal_id="POLIS",
            ),
            display_name="Polis",
        )
    )

    registry = ReasoningPolicyRegistry()

    registry.register(
        MentionPolicy(),
    )

    reasoner = RuleBasedReasoningService(
        registry,
    )

    decision = reasoner.reason(event)

    assert decision.action == ReasoningAction.REPLY
def create_event(
    text: str,
) -> CommunicationEvent:

    return CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="U1",
            ),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="C1",
            ),
            name="general",
            channel_type="public",
        ),
        content=Content(
            body=text,
        ),
    )


def test_ignore_normal_message():

    
    registry = ReasoningPolicyRegistry()

    registry.register(
        MentionPolicy(),
    )

    reasoner = RuleBasedReasoningService(
        registry,
    )
    decision = reasoner.reason(
        create_event(
            "Hello everyone",
        )
    )

    assert decision.action == ReasoningAction.IGNORE