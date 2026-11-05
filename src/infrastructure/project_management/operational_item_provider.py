"""
Internal Operational Items Project Management Provider Adapter.
"""

from __future__ import annotations

import logging
from typing import Any

from domain.operations.enums import OperationalItemPriority, OperationalItemStatus, OperationalItemType
from domain.project_management.models import Milestone, Project, Sprint, WorkItem
from .base import ProjectManagementProvider

logger = logging.getLogger(__name__)


class OperationalItemProjectProvider(ProjectManagementProvider):
    """
    Adapts POLIS internal OperationalItemRepository items into standardized WorkItem representations.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self._repo = repository

    def is_connected(self) -> bool:
        return self._repo is not None

    def get_projects(self) -> list[Project]:
        return [
            Project(
                project_id="polis_core_ops",
                name="POLIS Operations & Initiatives",
                key="OPS",
                description="Internal operational tasks, decisions, and overarching initiatives",
                status="active",
                source_provider="operational_items",
            )
        ]

    def get_active_sprints(self, project_id: str | None = None) -> list[Sprint]:
        return [
            Sprint(
                sprint_id="current_sprint",
                name="Current Active Sprint",
                project_id="polis_core_ops",
                status="active",
                goal="Core Team Initiatives & Hardening",
            )
        ]

    def get_work_items(
        self,
        project_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[WorkItem]:
        if not self.is_connected():
            return []

        try:
            items = self._repo.find_all()
        except Exception as exc:
            logger.warning("Error fetching operational items: %s", exc)
            return []

        work_items: list[WorkItem] = []
        for op in items:
            raw_status = op.status.value if hasattr(op.status, "value") else str(op.status)
            norm_status = self._normalize_status(op.status)
            raw_prio = op.priority.value if hasattr(op.priority, "value") else str(op.priority)
            norm_prio = self._normalize_priority(op.priority)

            meta = dict(getattr(op, "metadata", {}) or {})
            is_overarching = bool(
                meta.get("is_overarching")
                or meta.get("item_type") in ("initiative", "epic")
                or getattr(op, "item_type", None) == OperationalItemType.DECISION
                or "initiative" in op.summary.lower()
                or "migration" in op.summary.lower()
                or "redesign" in op.summary.lower()
                or "automation" in op.summary.lower()
            )

            # Blockers from metadata
            blockers = list(meta.get("blockers") or [])
            dependencies = list(meta.get("dependencies") or [])

            # Item ID
            item_id = str(getattr(op, "identifier", None) or getattr(op, "item_id", "unknown"))

            work_items.append(
                WorkItem(
                    item_id=item_id,
                    title=op.summary,
                    item_type="initiative" if is_overarching else "task",
                    status=norm_status,
                    source_status=raw_status.title(),
                    priority=norm_prio,
                    source_priority=raw_prio.title(),
                    owner_id=op.owner_id,
                    owner_name=op.owner_name,
                    project_id="polis_core_ops",
                    project_name="POLIS Operations & Initiatives",
                    sprint_id="current_sprint",
                    sprint_name="Current Active Sprint",
                    deadline=op.due_at,
                    is_overarching=is_overarching,
                    dependencies=dependencies,
                    blockers=blockers,
                    labels=list(meta.get("labels", [])),
                    updated_at=getattr(op, "updated_at", None),
                    url=meta.get("url"),
                    source_provider="operational_items",
                    metadata=meta,
                )
            )

        return work_items

    @staticmethod
    def _normalize_status(status: Any) -> str:
        s = (status.value if hasattr(status, "value") else str(status)).lower()
        if s in ("in_progress", "active", "in review"):
            return "in_progress"
        if s in ("completed", "closed", "done", "accepted"):
            return "completed"
        if s in ("cancelled", "superseded", "rejected"):
            return "cancelled"
        if s in ("blocked", "impeded"):
            return "blocked"
        return "open"

    @staticmethod
    def _normalize_priority(prio: Any) -> str:
        p = (prio.value if hasattr(prio, "value") else str(prio)).lower()
        if p in ("critical", "highest", "p0", "urgent"):
            return "critical"
        if p in ("high", "p1"):
            return "high"
        if p in ("medium", "p2", "normal"):
            return "medium"
        return "low"
