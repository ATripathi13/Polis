from domain.common.identifier import Identifier

from domain.observation import (
    KnowledgeObservationRule,
    ObservationType,
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
class FakeKnowledgeUnderstanding:
    def analyze(self, text):
        return {
            "is_knowledge": True,
            "summary": "We use PostgreSQL.",
            "confidence": 0.95,
        }

def test_extract_knowledge_observation():

    communication = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="john",
            ),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="general",
            ),
            name="general",
            channel_type="slack",
        ),
        content=Content(
            body="We use PostgreSQL.",
        ),
    )

    rule = KnowledgeObservationRule(
        FakeKnowledgeUnderstanding(),
    )

    observations = rule.extract(
        communication,
    )

    assert len(observations) == 1

    assert (
        observations[0].observation_type
        == ObservationType.KNOWLEDGE
    )

    assert (
        observations[0].summary
        == "We use PostgreSQL."
    )