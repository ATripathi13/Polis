"""
Routes explicit POLIS Slack messages to the conversational
cognitive engine.
"""

from __future__ import annotations

from application.cognitive import (
    CognitiveEngine,
)

from domain.reasoning import (
    ConversationContext,
    Question,
)
from domain.reasoning.repositories import (
    ConversationRepository,
)

from engines.slack.dto import (
    SlackMessage,
)

from engines.slack.services import (
    SlackResponder,
)


class SlackIntentRouter:
    """
    Routes explicitly addressed POLIS messages
    to the cognitive engine.
    """

    def __init__(
        self,
        engine: CognitiveEngine,
        responder: SlackResponder,
        connector,
        conversation_repository: ConversationRepository,
    ) -> None:

        self._engine = engine

        self._responder = responder

        self._connector = connector

        self._conversation_repository = conversation_repository

    def handle(
        self,
        message: SlackMessage,
    ) -> None:
        """
        Handle an explicit POLIS Slack message.

        The Slack listener is responsible for determining
        whether POLIS was mentioned. Once this method is
        called, the message is treated as a conversational
        request regardless of punctuation.
        """

        text = message.text.strip()

        if not text:
            return

        thread_ts = message.thread_ts or message.ts

        conversation_context = self._conversation_repository.get(
            channel_id=message.channel,
            thread_ts=thread_ts,
        )

        if conversation_context is None:
            conversation_context = ConversationContext(
                user_id=message.user,
                channel_id=message.channel,
                thread_ts=thread_ts,
            )

        question = Question(
            text=text,
            context=conversation_context,
        )

        answer = self._engine.ask(
            question,
        )

        updated_context = conversation_context.add_exchange(
            user_message=text,
            assistant_message=answer.text,
        )

        self._conversation_repository.save(
            updated_context,
        )

        self._responder.reply(
            channel=message.channel,
            thread_ts=(
                message.thread_ts
                or message.ts
            ),
            text=answer.text,
        )