"""
Slack Application Service.
"""

from __future__ import annotations

from connectors.slack.models import SlackEvent
from connectors.slack.normalizers import SlackNormalizer

from engines.communication.application.services import (
    CommunicationService,
)
from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


class SlackService:
    """
    Coordinates Slack ingestion.
    """

    def __init__(
        self,
        normalizer: SlackNormalizer,
        communication_service: CommunicationService,
    ) -> None:
        self._normalizer = normalizer
        self._communication_service = communication_service

    def ingest(
        self,
        event: SlackEvent,
    ) -> CommunicationEvent:
        """
        Normalize and persist a Slack event.
        """

        communication = self._normalizer.normalize(event)

        from engines.communication.application.commands import (
            IngestCommunicationCommand,
        )

        command = IngestCommunicationCommand(
            event=communication,
        )

        return self._communication_service.process(
            command,
        )