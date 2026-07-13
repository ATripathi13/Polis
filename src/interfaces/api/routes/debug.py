"""
Debug API routes.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
)

from domain.knowledge import (
    KnowledgeRepository,
)

from interfaces.api.dependencies import (
    get_repository,
)

router = APIRouter(
    prefix="/debug",
    tags=["Debug"],
)

@router.get(
    "/knowledge",
)
def get_knowledge(
    repository: KnowledgeRepository = Depends(
        get_repository,
    ),
):
    knowledge = repository.all()
    return knowledge