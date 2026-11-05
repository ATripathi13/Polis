"""
Base interface for Project Management Providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from domain.project_management.models import Milestone, Project, Sprint, WorkItem


class ProjectManagementProvider(ABC):
    """
    Abstract adapter for project management integrations
    (Jira, Linear, GitHub Projects, Internal Operational Items).
    """

    @abstractmethod
    def get_projects(self) -> list[Project]:
        """Retrieve active projects."""
        raise NotImplementedError

    @abstractmethod
    def get_active_sprints(self, project_id: str | None = None) -> list[Sprint]:
        """Retrieve currently active sprints or cycles."""
        raise NotImplementedError

    @abstractmethod
    def get_work_items(
        self,
        project_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[WorkItem]:
        """Retrieve work items matching criteria."""
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        """Check whether provider is actively configured and reachable."""
        raise NotImplementedError
