"""
Linear Project Management Provider Adapter for POLIS.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests

from domain.project_management.models import Milestone, Project, Sprint, WorkItem
from .base import ProjectManagementProvider

logger = logging.getLogger(__name__)


class LinearProvider(ProjectManagementProvider):
    """
    Adapter for Linear GraphQL API.
    Required Configuration:
    - LINEAR_API_KEY
    """

    LINEAR_API_URL = "https://api.linear.app/graphql"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("LINEAR_API_KEY", "")

    def is_connected(self) -> bool:
        return bool(self._api_key)

    def _execute_query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
        }
        resp = requests.post(
            self.LINEAR_API_URL,
            headers=headers,
            json={"query": query, "variables": variables or {}},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    def get_projects(self) -> list[Project]:
        if not self.is_connected():
            return []
        query = """
        query {
            projects(first: 20) {
                nodes {
                    id
                    name
                    state
                    description
                }
            }
        }
        """
        try:
            data = self._execute_query(query)
            nodes = data.get("projects", {}).get("nodes", [])
            return [
                Project(
                    project_id=n.get("id", ""),
                    name=n.get("name", ""),
                    status=n.get("state", "active"),
                    description=n.get("description", ""),
                    source_provider="linear",
                )
                for n in nodes
            ]
        except Exception as exc:
            logger.warning("Linear get_projects error: %s", exc)
            return []

    def get_active_sprints(self, project_id: str | None = None) -> list[Sprint]:
        if not self.is_connected():
            return []
        query = """
        query {
            cycles(filter: { isActive: { eq: true } }) {
                nodes {
                    id
                    name
                    number
                    startsAt
                    endsAt
                }
            }
        }
        """
        try:
            data = self._execute_query(query)
            nodes = data.get("cycles", {}).get("nodes", [])
            return [
                Sprint(
                    sprint_id=c.get("id", ""),
                    name=f"Cycle {c.get('number', '')}: {c.get('name', '')}",
                    project_id=project_id or "",
                    status="active",
                    source_provider="linear",
                )
                for c in nodes
            ]
        except Exception as exc:
            logger.warning("Linear get_active_sprints error: %s", exc)
            return []

    def get_work_items(
        self,
        project_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[WorkItem]:
        if not self.is_connected():
            return []
        query = """
        query {
            issues(first: 50, filter: { state: { type: { nin: ["completed", "canceled"] } } }) {
                nodes {
                    id
                    title
                    priority
                    priorityLabel
                    state { name type }
                    assignee { id name }
                    project { id name }
                    cycle { id name }
                    dueDate
                    url
                    parent { id }
                }
            }
        }
        """
        try:
            data = self._execute_query(query)
            nodes = data.get("issues", {}).get("nodes", [])
            items: list[WorkItem] = []
            for issue in nodes:
                state_info = issue.get("state") or {}
                stype = state_info.get("type", "started")
                prio_val = issue.get("priority", 0)  # 1 = Urgent, 2 = High, 3 = Medium, 4 = Low
                prio_norm = "critical" if prio_val == 1 else "high" if prio_val == 2 else "medium" if prio_val == 3 else "low"
                assignee = issue.get("assignee") or {}
                proj = issue.get("project") or {}
                cycle = issue.get("cycle") or {}

                items.append(
                    WorkItem(
                        item_id=issue.get("id", ""),
                        title=issue.get("title", ""),
                        item_type="task" if issue.get("parent") else "initiative",
                        status="in_progress" if stype == "started" else "open",
                        source_status=state_info.get("name", "Started"),
                        priority=prio_norm,
                        source_priority=issue.get("priorityLabel", "Medium"),
                        owner_id=assignee.get("id"),
                        owner_name=assignee.get("name"),
                        project_id=proj.get("id", ""),
                        project_name=proj.get("name", ""),
                        sprint_id=cycle.get("id"),
                        sprint_name=cycle.get("name"),
                        is_overarching=not bool(issue.get("parent")),
                        url=issue.get("url"),
                        source_provider="linear",
                    )
                )
            return items
        except Exception as exc:
            logger.warning("Linear get_work_items error: %s", exc)
            return []
