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
from infrastructure.config.settings import get_settings
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
    ) -> None:

        self._engine = engine
        self._mapper = mapper
        self._settings = settings

    settings = get_settings()

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
        print(f"[SLACK] Incoming user : {message.user!r}")
        print(f"[SLACK] Bot user      : {self._settings.slack_bot_user_id!r}")
        print(f"[SLACK] Equal?        : {message.user == self._settings.slack_bot_user_id}")
        if message.user == self._settings.slack_bot_user_id:
            return
        communication = (
            self._mapper.to_communication(
                message,
            )
        )
        self._engine.learn(
            communication,
        )