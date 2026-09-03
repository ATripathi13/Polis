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

from application.cognitive import CognitiveEngine


class SlackService:
    """
    Coordinates Slack ingestion and POLIS cognitive processing.
    """

    def __init__(
        self,
        normalizer: SlackNormalizer,
        communication_service: CommunicationService,
        cognitive_engine: CognitiveEngine,
    ) -> None:
        self._normalizer = normalizer
        self._communication_service = communication_service
        self._cognitive_engine = cognitive_engine

    def ingest(
        self,
        event: SlackEvent,
    ) -> CommunicationEvent:
        """
        Normalize, persist, and send the communication
        through the POLIS cognitive pipeline.
        """

        communication = self._normalizer.normalize(
            event,
        )

        from engines.communication.application.commands import (
            IngestCommunicationCommand,
        )

        command = IngestCommunicationCommand(
            event=communication,
        )

        saved = self._communication_service.process(
            command,
        )

        # Send the communication into the POLIS
        # cognitive engine.
        self._cognitive_engine.learn(
            saved,
        )

        return saved

    def ask(
        self,
        question,
    ):
        return self._cognitive_engine.ask(
            question,
        )