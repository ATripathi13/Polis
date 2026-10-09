from domain.observation import (
    ObservationType,
)
from domain.observation.rules import (
    OrganizationalIntentObservationRule,
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
from domain.common.identifier import Identifier


class FakeIntentUnderstanding:
    def __init__(self, result):
        self.result = result

    def analyze(self, text):
        return self.result


def make_communication():
    return CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="1712345678.123456",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="john"),
            display_name="John",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="general"),
            name="general",
            channel_type="slack",
        ),
        content=Content(
            body="Please approve the deployment.",
        ),
    )


def test_extract_organizational_intent():
    rule = OrganizationalIntentObservationRule(
        FakeIntentUnderstanding(
            {
                "is_intent": True,
                "type": "approval",
                "summary": "Deployment approved.",
                "confidence": 0.95,
            }
        )
    )

    observations = rule.extract(make_communication())

    assert len(observations) == 1
    assert observations[0].observation_type == ObservationType.APPROVAL
    assert observations[0].summary == "Deployment approved."
    assert observations[0].confidence == 0.95
    assert observations[0].evidence == ["1712345678.123456"]


def test_unknown_intent_is_ignored():
    rule = OrganizationalIntentObservationRule(
        FakeIntentUnderstanding(
            {
                "is_intent": True,
                "type": "none",
                "summary": "",
                "confidence": 0.0,
            }
        )
    )

    observations = rule.extract(make_communication())

    assert observations == []
