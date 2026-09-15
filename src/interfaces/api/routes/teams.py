from __future__ import annotations

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
        return PlainTextResponse(
            content=validation_token,
            media_type="text/plain",
        )

    payload = await request.json()

    for notification in payload.get("value", []):
        client_state = notification.get("clientState")

        if client_state != "polis-teams-transcript":
            continue

        resource_data = notification.get("resourceData", {})

        transcript_id = resource_data.get("id")

        resource = notification.get("resource", "")

        if not transcript_id or not resource:
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
            continue

        print("Teams transcript notification parsed:")
        print("  user_id:", user_id)
        print("  online_meeting_id:", online_meeting_id)
        print("  transcript_id:", transcript_id)

        transcript = provider.get_transcript_by_notification(
            user_id=user_id,
            online_meeting_id=online_meeting_id,
            transcript_id=transcript_id,
        )

        if transcript is None:
            print("  transcript retrieval: NOT FOUND")
            continue

        print("  transcript retrieval: SUCCESS")
        print("  transcript length:", len(transcript.transcript))

        service.ingest(transcript)

        print("  transcript persistence: SUCCESS")

        communications = teams_service.ingest_transcript(
            transcript=transcript.transcript,
            meeting_id=online_meeting_id,
            transcript_id=transcript_id,
        )

        print("  communication events:", len(communications))
        print("  cognitive processing: SUCCESS")
    return {"status": "accepted"}