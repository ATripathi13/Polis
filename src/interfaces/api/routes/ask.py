"""
Question answering and knowledge intelligence API.
"""

from __future__ import annotations

from dataclasses import asdict
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from application.cognitive import (
    CognitiveEngine,
)
from domain.reasoning import (
    Question,
)
from domain.organization import (
    OrganizationEvent,
)
from interfaces.api.dependencies import (
    get_cognitive_engine,
    get_knowledge_agent,
)
from interfaces.api.models import (
    QuestionRequest,
    AnswerResponse,
    KnowledgeResultResponse,
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
    """
    Standard POLIS grounded question answering endpoint.
    """
    question = Question(
        text=request.question,
        target_user_id=request.employee_slack_user_id,
    )
    answer = engine.ask(
        question,
    )

    sources = []
    if hasattr(answer, "sources"):
        sources = [str(s) for s in answer.sources]

    return AnswerResponse(
        answer=answer.text,
    )


@router.post(
    "/knowledge",
    response_model=KnowledgeResultResponse,
)
def ask_knowledge(
    request: QuestionRequest,
    knowledge_agent=Depends(
        get_knowledge_agent,
    ),
):
    """
    Direct Knowledge Agent specialist intelligence endpoint.
    Returns structured knowledge status, confidence, traceable evidence,
    sources, contradictions, and gap analysis.
    """
    if knowledge_agent is None:
        raise HTTPException(
            status_code=503,
            detail="Knowledge Agent specialist is not configured.",
        )

    question = Question(
        text=request.question,
        target_user_id=request.employee_slack_user_id,
    )
    result = knowledge_agent.ask(
        question,
        employee_slack_user_id=request.employee_slack_user_id,
    )

    sources_data = [
        {
            "source_type": s.source_type,
            "document_name": s.document_name,
            "source_event_id": s.source_event_id,
            "authority": s.authority,
            "snippet": s.snippet,
        }
        for s in result.sources
    ]

    contradictions_data = [
        {
            "existing_knowledge": c.existing_knowledge,
            "new_knowledge": c.new_knowledge,
            "conflict_explanation": c.conflict_explanation,
            "supporting_evidence": c.supporting_evidence,
            "authority_info": c.authority_info,
            "recommended_resolution": c.recommended_resolution,
        }
        for c in result.contradictions
    ]

    return KnowledgeResultResponse(
        status=result.status.value if hasattr(result.status, "value") else str(result.status),
        answer=result.answer,
        confidence=result.confidence,
        evidence=result.evidence,
        sources=sources_data,
        contradictions=contradictions_data,
        knowledge_changes=result.knowledge_changes,
        missing_aspects=result.missing_aspects,
    )