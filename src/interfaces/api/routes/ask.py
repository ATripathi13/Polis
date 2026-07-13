"""
Question answering API.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
)

from application.cognitive import (
    CognitiveEngine,
)

from domain.reasoning import (
    Question,
)

from interfaces.api.dependencies import (
    get_cognitive_engine,
)

from interfaces.api.models import (
    QuestionRequest,
    AnswerResponse,
)
router = APIRouter(
    prefix="/ask",
    tags=["Question Answering"],
)

@router.post(
    "",
    response_model=AnswerResponse,
)
def ask(
    request: QuestionRequest,
    engine: CognitiveEngine = Depends(
        get_cognitive_engine,
    ),
):
    question = Question(
        text=request.question,
    )
    answer = engine.ask(
        question,
    )
    return AnswerResponse(
        answer=answer.text,
    )