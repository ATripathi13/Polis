"""
Slack connector.
"""

from __future__ import annotations

from application.cognitive import (
    CognitiveEngine,
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

class SlackConnector:
    """
    Receives Slack events and forwards
    them into the Polis Cognitive Engine.
    """
    def __init__(
        self,
        engine: CognitiveEngine,
        mapper: CommunicationMapper,
    ) -> None:

        self._engine = engine
        self._mapper = mapper
    def receive(
        self,
        message: SlackMessage,
    ) -> None:
        """
        Process an incoming Slack message.
        """
        # message = self._parser.parse(
        #     payload,
        # )
        communication = (
            self._mapper.to_communication(
                message,
            )
        )
        self._engine.learn(
            communication,
        )