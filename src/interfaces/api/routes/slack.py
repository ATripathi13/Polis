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

from interfaces.api.dependencies import (
    get_cognitive_engine,
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
from infrastructure.config.settings import get_settings
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
):  
    
    parser = SlackEventParser()
    message = parser.parse(payload,)
    print(message)
    connector = SlackConnector(engine,CommunicationMapper(),get_settings(),)
    client = SlackClient()
    responder = SlackResponder(client,)
    intent_router = SlackIntentRouter(
        engine=engine,
        responder=responder,
        connector=connector,
    )
    intent_router.handle(message,)
    return {"status": "accepted",}