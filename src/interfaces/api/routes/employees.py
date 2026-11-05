"""
HR & Team Directory Querying API endpoints.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from interfaces.api.dependencies import (
    get_team_directory_service,
    require_internal_api_key,
)

router = APIRouter(
    prefix="/employees",
    tags=["Team Directory"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.get("/search")
def search_employees(
    q: str = Query(..., description="Name, role, department, or skill keyword"),
    directory_service=Depends(get_team_directory_service),
):
    """Search employees by name, role, skill, or department."""
    if directory_service is None:
        raise HTTPException(status_code=503, detail="Team Directory Service is not configured.")

    resolved, candidates, clarification = directory_service.find_employee(q)
    if clarification:
        return {
            "status": "ambiguous",
            "clarification_prompt": clarification,
            "candidates": [
                {
                    "employee_id": c.employee_id,
                    "full_name": c.full_name,
                    "role": c.role,
                    "team": c.team,
                }
                for c in candidates
            ],
        }

    if not resolved:
        return {"status": "not_found", "message": f"No employee found matching '{q}'."}

    return {
        "status": "found",
        "employee": {
            "employee_id": resolved.employee_id,
            "full_name": resolved.full_name,
            "role": resolved.role,
            "department": resolved.department,
            "team": resolved.team,
            "working_hours": resolved.working_hours,
            "working_days": resolved.working_days,
            "time_zone": resolved.time_zone,
            "responsibilities": resolved.responsibilities,
            "skills": resolved.skills,
            "areas_of_ownership": resolved.areas_of_ownership,
            "email": resolved.email,
            "source": resolved.source,
        },
    }


@router.get("/{employee_id}")
def get_employee_profile(
    employee_id: str,
    directory_service=Depends(get_team_directory_service),
):
    """Retrieve full employee profile by employee ID or name."""
    if directory_service is None:
        raise HTTPException(status_code=503, detail="Team Directory Service is not configured.")

    resolved, _, _ = directory_service.find_employee(employee_id)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found.")

    return {
        "employee_id": resolved.employee_id,
        "full_name": resolved.full_name,
        "role": resolved.role,
        "department": resolved.department,
        "team": resolved.team,
        "reporting_manager": resolved.reporting_manager,
        "working_hours": resolved.working_hours,
        "working_days": resolved.working_days,
        "time_zone": resolved.time_zone,
        "responsibilities": resolved.responsibilities,
        "skills": resolved.skills,
        "areas_of_ownership": resolved.areas_of_ownership,
        "email": resolved.email,
        "slack_user_id": resolved.slack_user_id,
        "teams_user_id": resolved.teams_user_id,
        "source": resolved.source,
    }


@router.get("/{employee_id}/schedule")
def get_employee_schedule(
    employee_id: str,
    directory_service=Depends(get_team_directory_service),
):
    """Retrieve working hours, working days, and time zone for an employee."""
    if directory_service is None:
        raise HTTPException(status_code=503, detail="Team Directory Service is not configured.")

    resolved, _, _ = directory_service.find_employee(employee_id)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found.")

    return {
        "employee_id": resolved.employee_id,
        "full_name": resolved.full_name,
        "working_hours": resolved.working_hours,
        "working_days": resolved.working_days,
        "time_zone": resolved.time_zone,
    }


@router.get("/{employee_id}/responsibilities")
def get_employee_responsibilities(
    employee_id: str,
    directory_service=Depends(get_team_directory_service),
):
    """Retrieve primary responsibilities, skills, and areas of ownership for an employee."""
    if directory_service is None:
        raise HTTPException(status_code=503, detail="Team Directory Service is not configured.")

    resolved, _, _ = directory_service.find_employee(employee_id)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found.")

    return {
        "employee_id": resolved.employee_id,
        "full_name": resolved.full_name,
        "role": resolved.role,
        "responsibilities": resolved.responsibilities,
        "skills": resolved.skills,
        "areas_of_ownership": resolved.areas_of_ownership,
    }


@router.get("/{employee_id}/holidays")
def get_employee_holidays(
    employee_id: str,
    days_ahead: int = Query(default=30, ge=1, le=180),
    directory_service=Depends(get_team_directory_service),
):
    """Retrieve upcoming approved leaves and organizational holidays for an employee."""
    if directory_service is None:
        raise HTTPException(status_code=503, detail="Team Directory Service is not configured.")

    resolved, _, _ = directory_service.find_employee(employee_id)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found.")

    holidays = directory_service.get_upcoming_holidays_and_leaves(resolved, days_ahead=days_ahead)
    return {
        "employee_id": resolved.employee_id,
        "full_name": resolved.full_name,
        "days_ahead": days_ahead,
        "upcoming_leaves_and_holidays": holidays,
    }
