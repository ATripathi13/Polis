"""
Custom Roster API Provider Adapter for POLIS.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import requests

from domain.employee.models import EmployeeLeave, EmployeeProfile
from .base import EmployeeDirectoryProvider

logger = logging.getLogger(__name__)


class RosterApiDirectoryProvider(EmployeeDirectoryProvider):
    """
    Adapter for a custom organizational Roster HTTP API.
    Required Configuration:
    - ROSTER_API_URL
    - ROSTER_API_KEY (optional)
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._api_url = api_url if api_url is not None else os.environ.get("ROSTER_API_URL", "")
        self._api_key = api_key if api_key is not None else os.environ.get("ROSTER_API_KEY", "")

    def is_connected(self) -> bool:
        return bool(self._api_url)

    def get_employee(self, employee_id: str) -> EmployeeProfile | None:
        if not self.is_connected():
            return None
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            resp = requests.get(f"{self._api_url.rstrip('/')}/employees/{employee_id}", headers=headers, timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return EmployeeProfile(
                employee_id=str(data.get("id", employee_id)),
                full_name=data.get("name", ""),
                role=data.get("role", ""),
                department=data.get("department", ""),
                email=data.get("email"),
                source="Custom Roster API",
            )
        except Exception as exc:
            logger.warning("Roster API error for employee %s: %s", employee_id, exc)
            return None

    def search_employees(self, query: str) -> list[EmployeeProfile]:
        if not self.is_connected():
            return []
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            resp = requests.get(f"{self._api_url.rstrip('/')}/employees", params={"q": query}, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data) if isinstance(data, dict) else data
            return [
                EmployeeProfile(
                    employee_id=str(it.get("id")),
                    full_name=it.get("name", ""),
                    role=it.get("role", ""),
                    department=it.get("department", ""),
                    email=it.get("email"),
                    source="Custom Roster API",
                )
                for it in items
            ]
        except Exception as exc:
            logger.warning("Roster API search error: %s", exc)
            return []

    def get_leaves(
        self,
        employee_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[EmployeeLeave]:
        return []
