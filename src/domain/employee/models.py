"""
Employee and Directory domain models for POLIS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class EmployeeLeave:
    """Represents approved leave or scheduled time off for an employee."""
    leave_id: str
    employee_id: str
    leave_type: str  # e.g., "Annual Leave", "Sick Leave", "Personal Leave", "Approved Leave"
    start_date: date
    end_date: date
    status: str = "approved"  # "approved", "pending", "cancelled"
    notes: str = ""
    is_approved: bool = True


@dataclass
class EmployeeProfile:
    """
    Authoritative Employee Directory Profile for POLIS.
    """
    employee_id: str
    full_name: str
    preferred_name: str | None = None
    role: str = ""  # Official designation
    department: str = ""
    team: str = ""
    reporting_manager: str | None = None
    working_hours: str = "09:30 - 18:30"
    working_days: list[str] = field(
        default_factory=lambda: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    )
    time_zone: str = "Asia/Kolkata"
    responsibilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    areas_of_ownership: list[str] = field(default_factory=list)
    email: str | None = None
    slack_user_id: str | None = None
    teams_user_id: str | None = None
    source: str = "Internal Directory"
    metadata: dict[str, Any] = field(default_factory=dict)
