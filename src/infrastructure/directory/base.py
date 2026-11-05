"""
Base interface for Employee Directory Providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from domain.employee.models import EmployeeLeave, EmployeeProfile


class EmployeeDirectoryProvider(ABC):
    """
    Abstract adapter for retrieving employee profiles, organizational hierarchy,
    and leave information from authoritative directories (Internal, BambooHR, Workday, Roster API).
    """

    @abstractmethod
    def get_employee(self, employee_id: str) -> EmployeeProfile | None:
        """Retrieve employee by internal ID or platform ID."""
        raise NotImplementedError

    @abstractmethod
    def search_employees(self, query: str) -> list[EmployeeProfile]:
        """Search employees by name, role, or team."""
        raise NotImplementedError

    @abstractmethod
    def get_leaves(
        self,
        employee_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[EmployeeLeave]:
        """Retrieve scheduled leaves and approved time off for an employee."""
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        """Check whether this directory provider is actively configured and reachable."""
        raise NotImplementedError
