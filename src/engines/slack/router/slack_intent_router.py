"""
Routes Slack messages based on intent.
"""

from __future__ import annotations

from application.cognitive import (
    CognitiveEngine,
)

from domain.reasoning import (
    Question,
)

from engines.slack.dto import (
    SlackMessage,
)

from engines.slack.services import (
    SlackResponder,
)
class SlackIntentRouter:
    """
    Routes Slack messages to the
    appropriate cognitive operation.
    """
    def __init__(
        self,
        engine: CognitiveEngine,
        responder: SlackResponder,
        connector,
    ) -> None:

        self._engine = engine

        self._responder = responder

        self._connector = connector

    def handle(
        self,
        message: SlackMessage,
    ) -> None:
        """
        Handle an incoming Slack message.
        """
        text = message.text.strip()

        if not text:
            return
        if text.endswith("?"):

            question = Question(
                text=text,
            )

            answer = self._engine.ask(
                question,
            )

            self._responder.reply(
                channel=message.channel,
                thread_ts=(
                    message.thread_ts
                    or message.ts
                ),
                text=answer.text,
            )

            return
        self._connector.receive(
            message,
        )