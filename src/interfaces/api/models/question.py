"""
Question API models.
"""

from __future__ import annotations

from pydantic import BaseModel

class QuestionRequest(BaseModel):
    """
    Ask POLIS a question.
    """

    question: str


class AnswerResponse(BaseModel):
    """
    POLIS answer.
    """

    answer: str

