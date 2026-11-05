"""
BambooHR Directory Provider Adapter for POLIS.
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


class BambooHRDirectoryProvider(EmployeeDirectoryProvider):
    """
    Adapter for BambooHR API.
    Required Configuration:
    - BAMBOOHR_API_KEY
    - BAMBOOHR_SUBDOMAIN
    """

    def __init__(
        self,
        api_key: str | None = None,
        subdomain: str | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("BAMBOOHR_API_KEY", "")
        self._subdomain = subdomain if subdomain is not None else os.environ.get("BAMBOOHR_SUBDOMAIN", "")

    def is_connected(self) -> bool:
        return bool(self._api_key and self._subdomain)

    def _get_base_url(self) -> str:
        return f"https://api.bamboohr.com/api/gateway.php/{self._subdomain}/v1"

    def get_employee(self, employee_id: str) -> EmployeeProfile | None:
        if not self.is_connected():
            return None
        url = f"{self._get_base_url()}/employees/{employee_id}"
        headers = {"Accept": "application/json"}
        auth = (self._api_key, "x")
        try:
            resp = requests.get(url, headers=headers, auth=auth, timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return EmployeeProfile(
                employee_id=str(data.get("id", employee_id)),
                full_name=f"{data.get('firstName', '')} {data.get('lastName', '')}".strip(),
                preferred_name=data.get("preferredName"),
                role=data.get("jobTitle", ""),
                department=data.get("department", ""),
                team=data.get("division", ""),
                email=data.get("workEmail"),
                source="BambooHR",
            )
        except Exception as exc:
            logger.warning("BambooHR API error for employee %s: %s", employee_id, exc)
            return None

    def search_employees(self, query: str) -> list[EmployeeProfile]:
        if not self.is_connected() or not query.strip():
            return []
        url = f"{self._get_base_url()}/employees/directory"
        headers = {"Accept": "application/json"}
        auth = (self._api_key, "x")
        try:
            resp = requests.get(url, headers=headers, auth=auth, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            employees = data.get("employees", [])
            q = query.lower()
            results: list[EmployeeProfile] = []
            for emp in employees:
                fn = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip()
                if q in fn.lower() or q in emp.get("jobTitle", "").lower():
                    results.append(
                        EmployeeProfile(
                            employee_id=str(emp.get("id", "")),
                            full_name=fn,
                            role=emp.get("jobTitle", ""),
                            department=emp.get("department", ""),
                            email=emp.get("workEmail"),
                            source="BambooHR",
                        )
                    )
            return results
        except Exception as exc:
            logger.warning("BambooHR directory search error: %s", exc)
            return []

    def get_leaves(
        self,
        employee_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[EmployeeLeave]:
        if not self.is_connected():
            return []
        url = f"{self._get_base_url()}/time_off/whos_out/"
        params: dict[str, str] = {}
        if start_date:
            params["start"] = start_date.isoformat()
        if end_date:
            params["end"] = end_date.isoformat()
        headers = {"Accept": "application/json"}
        auth = (self._api_key, "x")
        try:
            resp = requests.get(url, headers=headers, params=params, auth=auth, timeout=10)
            resp.raise_for_status()
            items = resp.json()
            leaves: list[EmployeeLeave] = []
            for item in items:
                if str(item.get("employeeId")) == employee_id:
                    leaves.append(
                        EmployeeLeave(
                            leave_id=str(item.get("id", "")),
                            employee_id=employee_id,
                            leave_type=item.get("type", "Approved Leave"),
                            start_date=date.fromisoformat(item.get("start")),
                            end_date=date.fromisoformat(item.get("end")),
                            status="approved",
                            is_approved=True,
                        )
                    )
            return leaves
        except Exception as exc:
            logger.warning("BambooHR leave lookup error: %s", exc)
            return []
