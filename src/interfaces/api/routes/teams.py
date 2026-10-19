from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from api.dependencies import (
    get_meeting_transcript_provider,
    get_meeting_transcript_service,
    get_teams_service,
)
from application.meetings import (
    MeetingTranscriptService,
    MeetingTranscriptProvider,
)
from connectors.microsoft_teams.services import (
    TeamsService,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/teams",
    tags=["teams"],
)


@router.post("/webhook")
async def teams_webhook(
    request: Request,
    provider: MeetingTranscriptProvider = Depends(
        get_meeting_transcript_provider
    ),
    service: MeetingTranscriptService = Depends(
        get_meeting_transcript_service
    ),
    teams_service: TeamsService = Depends(
        get_teams_service
    ),
):
    validation_token = request.query_params.get("validationToken")

    if validation_token:
        logger.info(
            "Teams webhook validation request received",
            extra={
                "event": "teams_webhook_validation",
                "operation": "validate_webhook",
            },
        )
        return PlainTextResponse(
            content=validation_token,
            media_type="text/plain",
        )

    payload = await request.json()

    for notification in payload.get("value", []):
        client_state = notification.get("clientState")

        if client_state != "polis-teams-transcript":
            logger.debug(
                "Ignoring Teams webhook notification with unexpected clientState",
                extra={
                    "event": "teams_notification_ignored_client_state",
                    "operation": "filter_notification",
                    "client_state": client_state,
                },
            )
            continue

        resource_data = notification.get("resourceData", {})

        transcript_id = resource_data.get("id")

        resource = notification.get("resource", "")

        if not transcript_id or not resource:
            logger.warning(
                "Teams webhook notification missing required resource fields",
                extra={
                    "event": "teams_notification_missing_fields",
                    "operation": "validate_notification",
                    "transcript_id": transcript_id,
                    "has_resource": bool(resource),
                },
            )
            continue

        try:
            users_part, remainder = resource.split(
                "/onlineMeetings(",
                1,
            )

            user_id = users_part.removeprefix("users('").removesuffix("')")

            meeting_part, _ = remainder.split(
                ")/transcripts(",
                1,
            )

            online_meeting_id = meeting_part.strip("'")

        except ValueError:
            logger.warning(
                "Failed to parse Teams webhook notification resource URI",
                extra={
                    "event": "teams_resource_parse_error",
                    "operation": "parse_resource_uri",
                    "resource": resource,
                },
            )
            continue

        logger.info(
            "Teams transcript notification parsed for meeting %s (transcript_id=%s, user_id=%s)",
            online_meeting_id,
            transcript_id,
            user_id,
            extra={
                "event": "teams_notification_parsed",
                "operation": "parse_notification",
                "user_id": user_id,
                "online_meeting_id": online_meeting_id,
                "transcript_id": transcript_id,
            },
        )

        transcript = provider.get_transcript_by_notification(
            user_id=user_id,
            online_meeting_id=online_meeting_id,
            transcript_id=transcript_id,
        )

        if transcript is None:
            logger.warning(
                "Teams transcript not found for meeting %s (transcript_id=%s, user_id=%s)",
                online_meeting_id,
                transcript_id,
                user_id,
                extra={
                    "event": "teams_transcript_not_found",
                    "operation": "retrieve_transcript",
                    "user_id": user_id,
                    "online_meeting_id": online_meeting_id,
                    "transcript_id": transcript_id,
                },
            )
            continue

        transcript_len = len(transcript.transcript) if transcript.transcript else 0
        logger.info(
            "Teams transcript retrieved for meeting %s (transcript_id=%s, length=%d)",
            online_meeting_id,
            transcript_id,
            transcript_len,
            extra={
                "event": "teams_transcript_retrieved",
                "operation": "retrieve_transcript",
                "user_id": user_id,
                "online_meeting_id": online_meeting_id,
                "transcript_id": transcript_id,
                "transcript_length": transcript_len,
            },
        )

        service.ingest(transcript)

        logger.info(
            "Teams transcript persisted successfully for meeting %s (transcript_id=%s)",
            online_meeting_id,
            transcript_id,
            extra={
                "event": "teams_transcript_persisted",
                "operation": "persist_transcript",
                "online_meeting_id": online_meeting_id,
                "transcript_id": transcript_id,
            },
        )

        meeting_start_time = transcript.metadata.get(
            "meeting_started_at"
        )

        communications = teams_service.ingest_transcript(
            transcript=transcript.transcript,
            meeting_id=online_meeting_id,
            transcript_id=transcript_id,
            meeting_start_time=meeting_start_time,
            captured_at=transcript.captured_at,
        )

        event_count = len(communications) if communications else 0
        logger.info(
            (
                "Teams transcript processed into %d communication events "
                "for meeting %s (transcript_id=%s)"
            ),
            event_count,
            online_meeting_id,
            transcript_id,
            extra={
                "event": "teams_cognitive_processing_success",
                "operation": "process_transcript",
                "online_meeting_id": online_meeting_id,
                "transcript_id": transcript_id,
                "communication_event_count": event_count,
            },
        )

    return {"status": "accepted"}
