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
from application.activity import ActivityProcessor
from engines.slack.dto import SlackMessage


class SlackService:
    """
    Coordinates Slack ingestion and POLIS cognitive processing.
    """

    def __init__(
        self,
        normalizer: SlackNormalizer,
        communication_service: CommunicationService,
        cognitive_engine: CognitiveEngine,
        activity_processor: ActivityProcessor | None = None,
    ) -> None:
        self._normalizer = normalizer
        self._communication_service = communication_service
        self._cognitive_engine = cognitive_engine
        self._activity_processor = activity_processor

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

        if self._activity_processor is not None:
            self._activity_processor.process(
                SlackMessage(
                    user=event.user.user_id,
                    channel=event.channel.channel_id,
                    text=event.message.text,
                    ts=event.message.ts,
                    event_ts=event.message.ts,
                    thread_ts=event.message.thread_ts,
                    user_name=event.user.username,
                )
            )

        # Send the communication into the POLIS
        # cognitive engine.
        #
        # Knowledge enrichment is secondary to communication
        # persistence. If the LLM is unavailable, the raw
        # communication must still remain successfully ingested.
        try:
            self._cognitive_engine.learn(
                saved,
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to enrich Slack communication with cognitive learning"
            )

        return saved

    def ask(
        self,
        question,
    ):
        return self._cognitive_engine.ask(
            question,
        )