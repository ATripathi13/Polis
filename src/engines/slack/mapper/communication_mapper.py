"""
Maps Slack messages into CommunicationEvents.
"""

from __future__ import annotations

from domain.common.identifier import (
    Identifier,
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

from engines.slack.dto import (
    SlackMessage,
)

class CommunicationMapper:
    """
    Converts Slack DTOs into
    CommunicationEvents.
    """

    def to_communication(
    self,
    message: SlackMessage,
    ) -> CommunicationEvent:
        """
        Convert a Slack message into
        a CommunicationEvent.
        """
        actor = Actor(
            identity=CommunicationIdentity(
                internal_id=message.user,
                external_ids={
                    "slack": message.user,
                },
            ),
            display_name=message.user,
        )
        channel = Channel(
            identity=CommunicationIdentity(
                internal_id=message.channel,
                external_ids={
                    "slack": message.channel,
                },
            ),
            name=message.channel,
            channel_type="slack",
        )
        content = Content(
            body=message.text,
        )
        return CommunicationEvent.create(
            correlation_id=Identifier(),
            source=EventSource.SLACK,
            source_event_id=message.event_ts,
            actor=actor,
            channel=channel,
            content=content,
        )