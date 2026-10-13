"""
Question API models.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class QuestionRequest(BaseModel):
    """
    Ask POLIS a question.
    """

    question: str
    employee_slack_user_id: str | None = None


class AnswerResponse(BaseModel):
    """
    POLIS answer.
    """

    answer: str


class KnowledgeResultResponse(BaseModel):
    """
    Detailed Knowledge Agent intelligence result.
    """

    status: str
    answer: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_changes: list[dict[str, Any]] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)


class OperationsResultResponse(BaseModel):
    """
    Detailed Operations Agent intelligence response.
    """

    question: str
    evidence: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
