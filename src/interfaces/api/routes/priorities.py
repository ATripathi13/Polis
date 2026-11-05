"""
Core Team Priority Tracker API endpoints.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from interfaces.api.dependencies import (
    get_priority_ranking_service,
    require_internal_api_key,
)

router = APIRouter(
    prefix="/priorities",
    tags=["Core Team Priorities"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.get("/projects")
def get_projects(
    priority_service=Depends(get_priority_ranking_service),
):
    """Retrieve active projects across project management providers."""
    if priority_service is None:
        raise HTTPException(status_code=503, detail="Priority Ranking Service is not configured.")

    projects = []
    for prov in priority_service._providers:
        if prov.is_connected():
            try:
                projects.extend(prov.get_projects())
            except Exception:
                pass

    return {
        "project_count": len(projects),
        "projects": [
            {
                "project_id": p.project_id,
                "name": p.name,
                "key": p.key,
                "description": p.description,
                "status": p.status,
                "source_provider": p.source_provider,
            }
            for p in projects
        ],
    }


@router.get("/sprints")
def get_sprints(
    project_id: str | None = None,
    priority_service=Depends(get_priority_ranking_service),
):
    """Retrieve active sprints across connected project management providers."""
    if priority_service is None:
        raise HTTPException(status_code=503, detail="Priority Ranking Service is not configured.")

    sprints = []
    for prov in priority_service._providers:
        if prov.is_connected():
            try:
                sprints.extend(prov.get_active_sprints(project_id=project_id))
            except Exception:
                pass

    return {
        "sprint_count": len(sprints),
        "sprints": [
            {
                "sprint_id": s.sprint_id,
                "name": s.name,
                "project_id": s.project_id,
                "status": s.status,
                "goal": s.goal,
            }
            for s in sprints
        ],
    }


@router.get("/items")
def get_work_items(
    status_filter: str | None = Query(default=None, alias="status"),
    priority_service=Depends(get_priority_ranking_service),
):
    """Retrieve raw work items across project management providers."""
    if priority_service is None:
        raise HTTPException(status_code=503, detail="Priority Ranking Service is not configured.")

    items = priority_service.get_all_work_items()
    if status_filter:
        items = [it for it in items if it.status.lower() == status_filter.lower()]

    return {
        "item_count": len(items),
        "items": [
            {
                "item_id": it.item_id,
                "title": it.title,
                "item_type": it.item_type,
                "status": it.status,
                "priority": it.priority,
                "owner_name": it.owner_name,
                "project_name": it.project_name,
                "sprint_name": it.sprint_name,
                "deadline": it.deadline.isoformat() if it.deadline else None,
                "is_overarching": it.is_overarching,
                "source_provider": it.source_provider,
            }
            for it in items
        ],
    }


@router.get("/ranked")
def get_ranked_priorities(
    in_progress_only: bool = Query(default=False),
    overarching_focus: bool = Query(default=True),
    priority_service=Depends(get_priority_ranking_service),
):
    """
    Retrieve deterministically ranked work items with composite score breakdown.
    """
    if priority_service is None:
        raise HTTPException(status_code=503, detail="Priority Ranking Service is not configured.")

    ranked = priority_service.rank_work_items(
        overarching_focus=overarching_focus,
        in_progress_only=in_progress_only,
    )

    return {
        "item_count": len(ranked),
        "ranked_items": [
            {
                "rank": idx + 1,
                "score": r.score,
                "item_id": r.item.item_id,
                "title": r.item.title,
                "item_type": r.item.item_type,
                "status": r.item.source_status,
                "priority": r.item.source_priority,
                "owner": r.item.owner_name or r.item.owner_id,
                "project_sprint": f"{r.item.project_name or r.item.project_id}{f' / {r.item.sprint_name}' if r.item.sprint_name else ''}",
                "deadline": r.item.deadline.strftime("%b %d, %Y") if r.item.deadline else None,
                "reasons": r.reasons,
                "source": r.item.url or f"{r.item.source_provider} ({r.item.item_id})",
            }
            for idx, r in enumerate(ranked)
        ],
    }


@router.get("/highest-in-progress")
def get_highest_in_progress(
    priority_service=Depends(get_priority_ranking_service),
):
    """
    Retrieve the single highest-ranking overarching team task currently in progress.
    """
    if priority_service is None:
        raise HTTPException(status_code=503, detail="Priority Ranking Service is not configured.")

    formatted_response = priority_service.answer_priority_query("What is our highest-priority team task right now?")
    highest = priority_service.get_highest_ranking_in_progress_task()

    item_data = None
    if highest:
        it = highest.item
        item_data = {
            "item_id": it.item_id,
            "title": it.title,
            "status": it.source_status,
            "priority": it.source_priority,
            "owner": it.owner_name or it.owner_id or "Unassigned",
            "project_sprint": f"{it.project_name or it.project_id}{f' / {it.sprint_name}' if it.sprint_name else ''}",
            "deadline": it.deadline.strftime("%b %d, %Y") if it.deadline else None,
            "reasons": highest.reasons,
            "score": highest.score,
            "source": it.url or f"{it.source_provider} ({it.item_id})",
        }

    return {
        "highest_priority_item": item_data,
        "formatted_text": formatted_response,
    }
