from __future__ import annotations

from fastapi import APIRouter, Depends

from application.meetings import MeetingIntelligenceService
from api.dependencies import get_meeting_intelligence_service
from interfaces.api.models import AnswerResponse, MeetingIntelligenceResponse


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


@router.get(
    "/{meeting_id}/intelligence",
    response_model=MeetingIntelligenceResponse,
)
def meeting_intelligence(
    meeting_id: str,
    service: MeetingIntelligenceService = Depends(
        get_meeting_intelligence_service
    ),
):
    result = service.analyze(meeting_id)

    return MeetingIntelligenceResponse(
        summary=result.summary,
        topics=result.topics,
        decisions=result.decisions,
        action_items=result.action_items,
        risks=result.risks,
        open_questions=result.open_questions,
        confidence=result.confidence,
        evidence=result.evidence,
    )
