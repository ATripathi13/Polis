"""
Jira Project Management Provider Adapter for POLIS.
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


class JiraProvider(ProjectManagementProvider):
    """
    Adapter for Atlassian Jira Cloud REST API.
    Required Configuration:
    - JIRA_URL (e.g. https://your-domain.atlassian.net)
    - JIRA_EMAIL
    - JIRA_API_TOKEN
    """

    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self._url = (base_url or os.environ.get("JIRA_URL", "")).rstrip("/")
        self._email = email or os.environ.get("JIRA_EMAIL", "")
        self._token = api_token or os.environ.get("JIRA_API_TOKEN", "")

    def is_connected(self) -> bool:
        return bool(self._url and self._email and self._token)

    def _get_auth(self) -> tuple[str, str]:
        return (self._email, self._token)

    def get_projects(self) -> list[Project]:
        if not self.is_connected():
            return []
        try:
            resp = requests.get(
                f"{self._url}/rest/api/3/project",
                auth=self._get_auth(),
                headers={"Accept": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                Project(
                    project_id=p.get("id", ""),
                    name=p.get("name", ""),
                    key=p.get("key", ""),
                    status="active",
                    source_provider="jira",
                )
                for p in data
            ]
        except Exception as exc:
            logger.warning("Jira get_projects error: %s", exc)
            return []

    def get_active_sprints(self, project_id: str | None = None) -> list[Sprint]:
        if not self.is_connected():
            return []
        # Agile board sprint lookup
        return []

    def get_work_items(
        self,
        project_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[WorkItem]:
        if not self.is_connected():
            return []
        try:
            jql = "resolution = Unresolved ORDER BY priority DESC, updated DESC"
            if project_id:
                jql = f"project = '{project_id}' AND {jql}"
            resp = requests.post(
                f"{self._url}/rest/api/3/search",
                auth=self._get_auth(),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json={"jql": jql, "maxResults": 50},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            items: list[WorkItem] = []
            for issue in issues:
                fields = issue.get("fields", {})
                itype = fields.get("issuetype", {}).get("name", "Task")
                is_epic = itype.lower() in ("epic", "initiative")
                prio_name = fields.get("priority", {}).get("name", "Medium")
                status_name = fields.get("status", {}).get("name", "Open")
                assignee = fields.get("assignee") or {}

                items.append(
                    WorkItem(
                        item_id=issue.get("key", ""),
                        title=fields.get("summary", ""),
                        item_type="initiative" if is_epic else "task",
                        status="in_progress" if "progress" in status_name.lower() else "open",
                        source_status=status_name,
                        priority="critical" if "critical" in prio_name.lower() or "highest" in prio_name.lower() else "high" if "high" in prio_name.lower() else "medium",
                        source_priority=prio_name,
                        owner_id=assignee.get("accountId"),
                        owner_name=assignee.get("displayName"),
                        project_id=fields.get("project", {}).get("key", ""),
                        project_name=fields.get("project", {}).get("name", ""),
                        is_overarching=is_epic,
                        url=f"{self._url}/browse/{issue.get('key')}",
                        source_provider="jira",
                    )
                )
            return items
        except Exception as exc:
            logger.warning("Jira search issues error: %s", exc)
            return []
