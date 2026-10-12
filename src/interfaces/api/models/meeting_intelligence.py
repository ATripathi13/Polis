from __future__ import annotations

from pydantic import BaseModel, Field


class MeetingIntelligenceResponse(BaseModel):
    """Structured intelligence extracted from a meeting."""

    summary: str
    topics: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float
    evidence: list[str] = Field(default_factory=list)
