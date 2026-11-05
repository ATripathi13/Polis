"""
Workday Directory Provider Adapter for POLIS.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

from domain.employee.models import EmployeeLeave, EmployeeProfile
from .base import EmployeeDirectoryProvider

logger = logging.getLogger(__name__)


class WorkdayDirectoryProvider(EmployeeDirectoryProvider):
    """
    Adapter for Workday Human Capital Management (HCM) API.
    Required Configuration:
    - WORKDAY_API_ENDPOINT
    - WORKDAY_CLIENT_ID
    - WORKDAY_CLIENT_SECRET
    """

    def __init__(
        self,
        endpoint: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self._endpoint = endpoint if endpoint is not None else os.environ.get("WORKDAY_API_ENDPOINT", "")
        self._client_id = client_id if client_id is not None else os.environ.get("WORKDAY_CLIENT_ID", "")
        self._client_secret = client_secret if client_secret is not None else os.environ.get("WORKDAY_CLIENT_SECRET", "")

    def is_connected(self) -> bool:
        return bool(self._endpoint and self._client_id and self._client_secret)

    def get_employee(self, employee_id: str) -> EmployeeProfile | None:
        if not self.is_connected():
            return None
        # Workday REST worker endpoint lookup
        return None

    def search_employees(self, query: str) -> list[EmployeeProfile]:
        if not self.is_connected():
            return []
        return []

    def get_leaves(
        self,
        employee_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[EmployeeLeave]:
        if not self.is_connected():
            return []
        return []
