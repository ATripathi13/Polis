from connectors.slack.models import SlackEvent
from connectors.slack.models.channel import SlackChannel
from connectors.slack.models.message import SlackMessage as ConnectorSlackMessage
from connectors.slack.models.user import SlackUser
from connectors.slack.services.slack_service import SlackService


class FakeNormalizer:
    def normalize(self, event):
        return "saved-communication"


class FakeCommunicationService:
    def process(self, command):
        return "persisted-communication"


class FakeCognitiveEngine:
    def __init__(self):
        self.learned = []

    def learn(self, communication):
        self.learned.append(communication)


class FakeActivityProcessor:
    def __init__(self):
        self.messages = []

    def process(self, message):
        self.messages.append(message)


def test_slack_service_forwards_activity_to_people_processor():
    activity_processor = FakeActivityProcessor()
    cognitive_engine = FakeCognitiveEngine()

    service = SlackService(
        normalizer=FakeNormalizer(),
        communication_service=FakeCommunicationService(),
        cognitive_engine=cognitive_engine,
        activity_processor=activity_processor,
    )

    event = SlackEvent(
        user=SlackUser(
            user_id="U123",
            username="Akshat",
        ),
        channel=SlackChannel(
            channel_id="C123",
            name="general",
            is_private=False,
        ),
        message=ConnectorSlackMessage(
            text="starting work",
            ts="9999999999.002",
            thread_ts=None,
        ),
    )

    service.ingest(event)

    assert len(activity_processor.messages) == 1

    message = activity_processor.messages[0]

    assert message.user == "U123"
    assert message.channel == "C123"
    assert message.text == "starting work"
    assert message.ts == "9999999999.002"
    assert message.event_ts == "9999999999.002"
    assert message.user_name == "Akshat"

    assert cognitive_engine.learned == ["persisted-communication"]

def test_slack_service_continues_when_activity_processing_fails():
    class FailingActivityProcessor:
        def process(self, message):
            raise RuntimeError("activity failure")

    cognitive_engine = FakeCognitiveEngine()

    service = SlackService(
        normalizer=FakeNormalizer(),
        communication_service=FakeCommunicationService(),
        cognitive_engine=cognitive_engine,
        activity_processor=FailingActivityProcessor(),
    )

    event = SlackEvent(
        user=SlackUser(
            user_id="U123",
            username="Akshat",
        ),
        channel=SlackChannel(
            channel_id="C123",
            name="general",
        ),
        message=ConnectorSlackMessage(
            text="starting work",
            ts="9999999999.004",
            thread_ts=None,
        ),
    )

    service.ingest(event)

    assert cognitive_engine.learned == [
        "persisted-communication"
    ]
