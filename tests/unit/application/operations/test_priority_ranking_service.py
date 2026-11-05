"""
Unit tests for PriorityRankingService:
- Deterministic composite ranking calculation
- Priority normalization
- In-progress status filtering
- Overarching initiative ranking vs subtask
- Blocker and deadline handling
- Empty backlog handling
- Standardized output format
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from application.operations.priority_ranking_service import PriorityRankingService
from domain.project_management.models import WorkItem
from infrastructure.project_management.base import ProjectManagementProvider


class FakeProjectProvider(ProjectManagementProvider):
    def __init__(self, items: list[WorkItem] | None = None) -> None:
        self._items = items or []

    def is_connected(self) -> bool:
        return True

    def get_projects(self):
        return []

    def get_active_sprints(self, project_id=None):
        return []

    def get_work_items(self, project_id=None, sprint_id=None):
        return self._items


def test_priority_ranking_overarching_in_progress_ranks_highest():
    now = datetime.now(timezone.utc)

    # 1. Leaf subtask that is critical but is just a subtask
    item_subtask = WorkItem(
        item_id="TASK-1",
        title="Fix typo in CSS button",
        item_type="subtask",
        status="in_progress",
        source_status="In Progress",
        priority="critical",
        source_priority="P0",
        is_overarching=False,
        parent_id="INITIATIVE-1",
    )

    # 2. Overarching initiative in progress with active sprint and high priority
    item_initiative = WorkItem(
        item_id="INIT-1",
        title="Core Team Hardening & Natural Organizational Intelligence",
        item_type="initiative",
        status="in_progress",
        source_status="In Progress",
        priority="high",
        source_priority="High",
        is_overarching=True,
        sprint_id="sprint_42",
        sprint_name="Hardening Sprint",
        owner_name="Akshat Tripathi",
        deadline=now + timedelta(days=2),
    )

    # 3. Low priority open task
    item_backlog = WorkItem(
        item_id="TASK-2",
        title="Explore future UI framework",
        item_type="task",
        status="open",
        source_status="Open",
        priority="low",
        source_priority="Low",
        is_overarching=False,
    )

    provider = FakeProjectProvider([item_subtask, item_initiative, item_backlog])
    service = PriorityRankingService(providers=[provider])

    highest = service.get_highest_ranking_in_progress_task()
    assert highest is not None
    assert highest.item.item_id == "INIT-1"
    assert highest.item.title == "Core Team Hardening & Natural Organizational Intelligence"
    assert any("Overarching initiative" in r for r in highest.reasons)
    assert any("In Progress" in r or "in progress" in r for r in highest.reasons)


def test_priority_ranking_completed_items_excluded_from_highest():
    # An overarching item that is already completed should not rank as highest in progress
    item_done = WorkItem(
        item_id="INIT-DONE",
        title="Legacy VPS Setup",
        item_type="initiative",
        status="completed",
        source_status="Completed",
        priority="critical",
        source_priority="Critical",
        is_overarching=True,
    )
    item_active = WorkItem(
        item_id="TASK-ACTIVE",
        title="Active Twilio SMS Verification",
        item_type="task",
        status="in_progress",
        source_status="In Progress",
        priority="medium",
        source_priority="Medium",
        is_overarching=False,
    )

    provider = FakeProjectProvider([item_done, item_active])
    service = PriorityRankingService(providers=[provider])

    highest = service.get_highest_ranking_in_progress_task()
    assert highest is not None
    assert highest.item.item_id == "TASK-ACTIVE"


def test_priority_ranking_empty_backlog_handled_gracefully():
    provider = FakeProjectProvider([])
    service = PriorityRankingService(providers=[provider])

    highest = service.get_highest_ranking_in_progress_task()
    assert highest is None

    ans = service.answer_priority_query("What is our highest-priority team task right now?")
    assert "No active tasks currently recorded" in ans
    assert "Backlog empty" in ans


def test_priority_ranking_answer_format():
    item = WorkItem(
        item_id="PROJ-101",
        title="Backend Database Migration",
        item_type="initiative",
        status="in_progress",
        source_status="In Progress",
        priority="high",
        source_priority="P1 - High",
        owner_name="Hemant Kumar Sah",
        project_name="POLIS Core",
        sprint_name="Sprint 14",
        deadline=datetime(2026, 11, 15, tzinfo=timezone.utc),
        is_overarching=True,
        url="https://jira.example.com/browse/PROJ-101",
    )
    provider = FakeProjectProvider([item])
    service = PriorityRankingService(providers=[provider])

    answer = service.answer_priority_query("What is our highest-ranking overarching task currently in progress?")

    # Required output format elements:
    assert "**Highest Priority Team Task:** Backend Database Migration" in answer
    assert "**Status:** In Progress" in answer
    assert "**Priority:** P1 - High" in answer
    assert "**Owner:** Hemant Kumar Sah" in answer
    assert "**Project / Sprint:** POLIS Core / Sprint 14" in answer
    assert "**Deadline:** Nov 15, 2026" in answer
    assert "**Reason for Ranking:**" in answer
    assert "**Source:** https://jira.example.com/browse/PROJ-101" in answer


def test_priority_ranking_top_five_active_items():
    items = [
        WorkItem(
            item_id=f"TASK-{i}",
            title=f"Active task {i}",
            item_type="task",
            status="in_progress" if i % 2 else "open",
            source_status="In Progress" if i % 2 else "Open",
            priority="high" if i == 1 else "medium",
            source_priority="High" if i == 1 else "Medium",
            owner_name=f"Owner {i}",
            is_overarching=False,
        )
        for i in range(1, 8)
    ]
    items.append(
        WorkItem(
            item_id="TASK-DONE",
            title="Completed task",
            item_type="task",
            status="completed",
            source_status="Completed",
            priority="critical",
            source_priority="Critical",
            is_overarching=True,
        )
    )

    service = PriorityRankingService(providers=[FakeProjectProvider(items)])
    answer = service.answer_priority_query("What are the top 5 active priorities?")

    assert "**Top 5 Active Team Priorities:**" in answer
    assert answer.count("**Status:**") == 5
    assert "Completed task" not in answer
