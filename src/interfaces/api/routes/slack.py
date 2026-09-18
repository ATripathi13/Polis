"""
Slack API routes.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
)

from application.cognitive import (
    CognitiveEngine,
)

from application.activity.activity_processor import (
    ActivityProcessor,
)

from interfaces.api.dependencies import (
    get_cognitive_engine,
    get_activity_processor,
)

from interfaces.api.models import (
    SlackEventRequest,
)

from engines.slack.connector import (
    SlackConnector,
)

from engines.slack.mapper import (
    CommunicationMapper,
)

from engines.slack.parser import (
    SlackEventParser,
)

from engines.slack.services import (
    SlackClient,
    SlackResponder,
)

from engines.slack.router import (
    SlackIntentRouter,
)

from infrastructure.config.settings import (
    get_settings,
)


router = APIRouter(
    prefix="/connectors/slack",
    tags=["Slack"],
)


@router.post(
    "/events",
)
async def receive_event(
    payload: SlackEventRequest,
    engine: CognitiveEngine = Depends(
        get_cognitive_engine,
    ),
    activity_processor: ActivityProcessor = Depends(
        get_activity_processor,
    ),
):
    identity_service = SlackIdentityService()
    parser = SlackEventParser()

    message = parser.parse(
        payload,
    )

    print(message)

    connector = SlackConnector(
        engine,
        CommunicationMapper(),
        get_settings(),
        activity_processor,
    )

    client = SlackClient()

    responder = SlackResponder(
        client,
    )

    intent_router = SlackIntentRouter(
        engine=engine,
        responder=responder,
        connector=connector,
    )

    intent_router.handle(
        message,
    )
    conversation_repository = get_conversation_repository()
    return {
        "status": "accepted",
    }