"""
Slack → CommunicationEvent normalizer.
"""

from __future__ import annotations

import re
from typing import Any

from domain.common.identifier import Identifier

from connectors.slack.models import SlackEvent

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.enums import (
    EventSource,
)
from engines.communication.domain.value_objects import (
    CommunicationIdentity,
    Mention,
)

class SlackNormalizer:
    """
    Converts Slack connector models into
    CommunicationEvent aggregates.
    """

    def __init__(
        self,
        identity_service: Any | None = None,
    ) -> None:
        self._identity_service = identity_service

    def normalize(
        self,
        event: SlackEvent,
    ) -> CommunicationEvent:
        """
        Convert a SlackEvent into a CommunicationEvent.
        """

        mentions: list[Mention] = []
        raw_text = event.message.text or ""

        # Extract all Slack mentions: <@U123456> or <@U123456|display_name>
        matches = re.finditer(r"<@([A-Za-z0-9_\-]+)(?:\|([^>]+))?>", raw_text)
        seen_user_ids: set[str] = set()

        for match in matches:
            mentioned_id = match.group(1).strip()
            if not mentioned_id or mentioned_id in seen_user_ids:
                continue
            seen_user_ids.add(mentioned_id)

            display_name = (match.group(2) or "").strip()
            if not display_name and self._identity_service is not None:
                try:
                    if hasattr(self._identity_service, "get_display_name"):
                        resolved = self._identity_service.get_display_name(mentioned_id)
                        if resolved:
                            display_name = str(resolved).strip()
                except Exception:
                    pass

            if not display_name:
                display_name = mentioned_id

            mentions.append(
                Mention(
                    identity=CommunicationIdentity(
                        internal_id=mentioned_id,
                        external_ids={"slack": mentioned_id},
                        metadata={
                            "platform": "slack",
                            "slack_user_id": mentioned_id,
                        },
                    ),
                    display_name=display_name,
                )
            )

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
            mentions=mentions,
        )