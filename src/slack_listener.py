"""
POLIS Slack Socket Mode process.
"""

from application.bootstrap.bootstrap import bootstrap

from connectors.slack.normalizers import SlackNormalizer
from connectors.slack.services import SlackService
from connectors.slack.socket_mode import SlackSocketMode

from engines.communication.application.services import (
    CommunicationService,
)

from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)

from domain.events import (
    EventDispatcher,
    EventRegistry,
)

from engines.communication.handlers import (
    CommunicationCreatedHandler,
)

from engines.communication.domain.events import (
    CommunicationCreatedEvent,
)


def create_listener():

    application = bootstrap()

    cognitive_engine = application.engine

    repository = InMemoryCommunicationRepository()

    registry = EventRegistry()

    registry.register(
        CommunicationCreatedEvent,
        CommunicationCreatedHandler(),
    )

    dispatcher = EventDispatcher(
        registry,
    )

    communication_service = CommunicationService(
        repository=repository,
        dispatcher=dispatcher,
    )

    normalizer = SlackNormalizer()

    slack_service = SlackService(
        normalizer=normalizer,
        communication_service=communication_service,
        cognitive_engine=cognitive_engine,
    )

    return SlackSocketMode(
        slack_service,
    )


if __name__ == "__main__":

    print("Starting POLIS Slack Socket Mode...")

    listener = create_listener()

    print("POLIS Slack listener started.")

    listener.start()