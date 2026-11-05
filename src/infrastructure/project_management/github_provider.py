"""
GitHub Projects and Issues Provider Adapter for POLIS.
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


class GitHubProjectsProvider(ProjectManagementProvider):
    """
    Adapter for GitHub Projects v2 / Issues GraphQL API.
    Required Configuration:
    - GITHUB_TOKEN
    - GITHUB_ORG
    """

    GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(
        self,
        token: str | None = None,
        org: str | None = None,
    ) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._org = org or os.environ.get("GITHUB_ORG", "")

    def is_connected(self) -> bool:
        return bool(self._token and self._org)

    def get_projects(self) -> list[Project]:
        if not self.is_connected():
            return []
        return []

    def get_active_sprints(self, project_id: str | None = None) -> list[Sprint]:
        if not self.is_connected():
            return []
        return []

    def get_work_items(
        self,
        project_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[WorkItem]:
        if not self.is_connected():
            return []
        return []
