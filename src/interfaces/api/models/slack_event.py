"""
Slack Events API request models.
"""

from __future__ import annotations

from pydantic import BaseModel

class SlackEvent(BaseModel):
    """
    Slack event payload.
    """

    type: str

    user: str

    channel: str

    text: str

    ts: str

    event_ts: str

    thread_ts: str | None = None

class SlackEventRequest(BaseModel):
    """
    Slack Events API request.
    """

    type: str

    event: SlackEvent