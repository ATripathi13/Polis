"""
Conversation Monitoring, Retrieval, and Summarization API endpoints.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from interfaces.api.dependencies import (
    get_conversation_summarizer_service,
    require_internal_api_key,
)

router = APIRouter(
    prefix="/conversations",
    tags=["Conversations"],
    dependencies=[Depends(require_internal_api_key)],
)


class ChannelHistoryRequest(BaseModel):
    channel_id: str = Field(description="Channel ID to query (e.g., C0BG7NWMD6D)")
    requesting_user_id: str = Field(description="ID of requesting user for authorization verification")
    oldest: str | None = Field(default=None, description="Unix timestamp oldest boundary")
    latest: str | None = Field(default=None, description="Unix timestamp latest boundary")
    limit: int = Field(default=50, ge=1, le=200)
    platform: str = Field(default="slack")
    team_id: str | None = None


class ThreadRepliesRequest(BaseModel):
    channel_id: str
    thread_ts: str
    requesting_user_id: str
    oldest: str | None = None
    latest: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    platform: str = Field(default="slack")


class ConversationSummarizeRequest(BaseModel):
    channel_id: str
    requesting_user_id: str
    channel_name: str | None = None
    topic: str | None = None
    time_window: str = "today"
    platform: str = "slack"


class SendPrivateSummaryRequest(BaseModel):
    channel_id: str
    requesting_user_id: str
    channel_name: str | None = None
    topic: str | None = None
    time_window: str = "today"
    platform: str = "slack"


@router.post("/history")
def get_channel_history(
    request: ChannelHistoryRequest,
    summarizer_service=Depends(get_conversation_summarizer_service),
):
    """Retrieve authorized channel message history with pagination and time filters."""
    if summarizer_service is None:
        raise HTTPException(status_code=503, detail="Conversation Summarizer Service is not configured.")

    try:
        messages = summarizer_service.retrieve_channel_history(
            channel_id=request.channel_id,
            user_id=request.requesting_user_id,
            oldest=request.oldest,
            latest=request.latest,
            limit=request.limit,
            platform=request.platform,
            team_id=request.team_id,
        )
        return {
            "channel_id": request.channel_id,
            "message_count": len(messages),
            "messages": messages,
        }
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/replies")
def get_thread_replies(
    request: ThreadRepliesRequest,
    summarizer_service=Depends(get_conversation_summarizer_service),
):
    """Retrieve reply thread messages after verifying channel authorization."""
    if summarizer_service is None:
        raise HTTPException(status_code=503, detail="Conversation Summarizer Service is not configured.")

    if not summarizer_service.verify_channel_access(
        channel_id=request.channel_id,
        user_id=request.requesting_user_id,
        platform=request.platform,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    slack_client = getattr(summarizer_service, "_slack_client", None)
    if not slack_client or not hasattr(slack_client, "get_conversation_replies"):
        raise HTTPException(status_code=503, detail="Slack client replies retrieval not available.")

    try:
        res = slack_client.get_conversation_replies(
            channel=request.channel_id,
            ts=request.thread_ts,
            oldest=request.oldest,
            latest=request.latest,
            limit=request.limit,
        )
        return res
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/summarize")
def summarize_conversation(
    request: ConversationSummarizeRequest,
    summarizer_service=Depends(get_conversation_summarizer_service),
):
    """
    Produce an evidence-grounded summary distinguishing discussion points, confirmed decisions,
    suggestions, action items, explicit owners, and unresolved questions.
    """
    if summarizer_service is None:
        raise HTTPException(status_code=503, detail="Conversation Summarizer Service is not configured.")

    try:
        summary = summarizer_service.execute_private_summary_workflow(
            channel_id=request.channel_id,
            requesting_user_id=request.requesting_user_id,
            channel_name=request.channel_name or request.channel_id,
            topic=request.topic or "",
            time_window=request.time_window,
            platform=request.platform,
            send_private_dm=False,
        )
        return {
            "title": summary.title,
            "discussion_points": summary.discussion_points,
            "confirmed_decisions": summary.confirmed_decisions,
            "suggestions": summary.suggestions,
            "action_items": summary.action_items,
            "unresolved_questions": summary.unresolved_questions,
            "participants": summary.participants,
            "time_window": summary.time_window,
            "source_channels": summary.source_channels,
            "formatted_text": summary.formatted_text,
        }
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/send-summary")
def send_private_summary(
    request: SendPrivateSummaryRequest,
    summarizer_service=Depends(get_conversation_summarizer_service),
):
    """
    Execute complete secure workflow:
    Authorization -> History Retrieval -> Privacy Filtering -> Summarization -> Private DM Delivery.
    """
    if summarizer_service is None:
        raise HTTPException(status_code=503, detail="Conversation Summarizer Service is not configured.")

    try:
        summary = summarizer_service.execute_private_summary_workflow(
            channel_id=request.channel_id,
            requesting_user_id=request.requesting_user_id,
            channel_name=request.channel_name or request.channel_id,
            topic=request.topic or "",
            time_window=request.time_window,
            platform=request.platform,
            send_private_dm=True,
        )
        return {
            "status": "delivered" if summary.delivered_privately else "completed_not_delivered",
            "delivered_privately": summary.delivered_privately,
            "delivery_channel_id": summary.delivery_channel_id,
            "formatted_text": summary.formatted_text,
        }
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
