from __future__ import annotations

from fastapi import APIRouter, Depends

from application.meetings import MeetingIntelligenceService
from api.dependencies import get_meeting_intelligence_service
from interfaces.api.models import AnswerResponse


router = APIRouter(
    prefix="/meetings",
    tags=["meetings"],
)


@router.get(
    "/{meeting_id}/summary",
    response_model=AnswerResponse,
)
def meeting_summary(
    meeting_id: str,
    service: MeetingIntelligenceService = Depends(
        get_meeting_intelligence_service
    ),
):
    answer = service.summarize(
        meeting_id,
    )

    return AnswerResponse(
        answer=answer.text,
    )
