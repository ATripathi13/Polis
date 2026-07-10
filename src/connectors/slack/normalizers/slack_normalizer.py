"""
Slack → CommunicationEvent normalizer.
"""

from __future__ import annotations

from domain.common.identifier import Identifier

from connectors.slack.models import SlackEvent

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.enums import (
    EventSource,
)

class SlackNormalizer:
    """
    Converts Slack connector models into
    CommunicationEvent aggregates.
    """

    def normalize(
        self,
        event: SlackEvent,
    ) -> CommunicationEvent:
        """
        Convert a SlackEvent into a CommunicationEvent.
        """

        return CommunicationEvent.create(
            correlation_id=Identifier(
                business_id=event.message.thread_ts
                or event.message.ts,
            ),
            source=EventSource.SLACK,
            source_event_id=event.message.ts,
            actor=event.user.to_actor(),
            channel=event.channel.to_channel(),
            content=event.message.to_content(),
        )