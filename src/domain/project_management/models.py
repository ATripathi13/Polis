"""
Project Management and Work Item domain models for POLIS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Project:
    project_id: str
    name: str
    key: str = ""
    description: str = ""
    status: str = "active"
    source_provider: str = ""


@dataclass
class Sprint:
    sprint_id: str
    name: str
    project_id: str
    status: str = "active"  # "active", "future", "closed"
    start_date: datetime | None = None
    end_date: datetime | None = None
    goal: str = ""


@dataclass
class Milestone:
    milestone_id: str
    title: str
    project_id: str
    due_date: datetime | None = None
    status: str = "open"


@dataclass
class WorkItem:
    """
    Standardized work item across Jira, Linear, GitHub Projects,
    and internal Operational Items.
    """
    item_id: str
    title: str
    item_type: str = "task"  # "initiative", "epic", "task", "subtask", "story", "bug"
    status: str = "open"  # Normalized: "in_progress", "open", "blocked", "completed", "closed"
    source_status: str = "Open"
    priority: str = "medium"  # Normalized: "critical", "high", "medium", "low"
    source_priority: str = "Medium"
    owner_id: str | None = None
    owner_name: str | None = None
    project_id: str = ""
    project_name: str = ""
    sprint_id: str | None = None
    sprint_name: str | None = None
    deadline: datetime | None = None
    is_overarching: bool = False  # True for initiatives, epics, root workstreams
    parent_id: str | None = None
    dependencies: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    updated_at: datetime | None = None
    url: str | None = None
    source_provider: str = "operational_items"
    metadata: dict[str, Any] = field(default_factory=dict)
