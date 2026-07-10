from fastapi import APIRouter, Depends

from api.dependencies import (
    get_slack_service,
)

from connectors.slack.services import SlackService

from connectors.slack.models import SlackEvent
from connectors.slack.normalizers import SlackNormalizer

from engines.communication.application.services import (
    CommunicationService,
)

router = APIRouter(
    prefix="/connectors/slack",
    tags=["Slack"],
)


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Slack Connector",
    }


@router.post("/events")
async def receive_event(
    event: SlackEvent,
    slack_service: SlackService = Depends(
        get_slack_service,
    ),
):
    saved = slack_service.ingest(event)

    return {
        "status": "success",
        "correlation_id": saved.correlation_id.business_id,
        "source": saved.source.value,
    }