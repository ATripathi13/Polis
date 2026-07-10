"""
Communication Application Service.
"""

from domain.events import EventDispatcher

from engines.communication.application.commands import (
    IngestCommunicationCommand,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from engines.communication.domain.repositories import (
    CommunicationRepository,
)

class CommunicationService:
    """
    Application service responsible for
    processing communication events.
    """

    def __init__(
        self,
        repository: CommunicationRepository,
        dispatcher: EventDispatcher,
    ) -> None:
        self._repository = repository
        self._dispatcher = dispatcher
    def process(
        self,
        command: IngestCommunicationCommand,
    ) -> CommunicationEvent:
        """
        Process an incoming communication.
        """

        communication = self._repository.save(
            command.event,
        )

        for event in communication.pull_domain_events():
            self._dispatcher.dispatch(event)

        return communication