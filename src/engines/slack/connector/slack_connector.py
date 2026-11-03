"""
Slack connector.
"""

from __future__ import annotations

from application.cognitive import (
    CognitiveEngine,
)

from application.activity import (
    ActivityProcessor,
)

from engines.slack.dto import (
    SlackMessage,
)

from engines.slack.mapper import (
    CommunicationMapper,
)

from engines.slack.parser import (
    SlackEventParser,
)

from interfaces.api.models import (
    SlackEventRequest,
)
from infrastructure.config.settings import get_settings

import logging

logger = logging.getLogger(__name__)


class SlackConnector:
    """
    Receives Slack events and forwards
    them into the Polis Cognitive Engine.
    """
    def __init__(
        self,
        engine: CognitiveEngine,
        mapper: CommunicationMapper,
        settings: get_settings,
        activity_processor: ActivityProcessor,
    ) -> None:

        self._engine = engine
        self._mapper = mapper
        self._settings = settings
        self._activity_processor = activity_processor

    settings = get_settings()

    def receive(
        self,
        message: SlackMessage,
    ) -> None:

        logger.debug(
            "SlackConnector received message from user %s (bot: %s)",
            message.user,
            self._settings.slack_bot_user_id,
            extra={"operation": "slack_connector_receive", "user_id": message.user},
        )

        if message.user == self._settings.slack_bot_user_id:
            return

        self._activity_processor.process(
            message,
        )

        communication = (
            self._mapper.to_communication(
                message,
            )
        )

        self._engine.learn(
            communication,
        )