"""
Unit tests for TeamDirectoryService and Employee Directory Querying.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock
import pytest

from application.directory.team_directory_service import TeamDirectoryService
from domain.employee.models import EmployeeLeave, EmployeeProfile
from infrastructure.directory.internal_provider import InternalEmployeeDirectoryProvider


def test_find_employee_exact_and_partial():
    service = TeamDirectoryService()

    # Exact full name
    emp, candidates, prompt = service.find_employee("Hemant Kumar Sah")
    assert prompt is None
    assert emp is not None
    assert emp.full_name == "Hemant Kumar Sah"
    assert emp.role == "Full Stack Engineer"

    # Partial / preferred name
    emp_akshat, _, _ = service.find_employee("Akshat")
    assert emp_akshat is not None
    assert emp_akshat.full_name == "Akshat Tripathi"


def test_find_employee_ambiguous_returns_clarification():
    # Setup directory with multiple "Vijay"
    provider = InternalEmployeeDirectoryProvider(
        employees=[
            {
                "employee_id": "EMP-01",
                "full_name": "Vijay Sharma",
                "role": "Frontend Lead",
                "team": "Web",
            },
            {
                "employee_id": "EMP-02",
                "full_name": "Vijay Kumar",
                "role": "Data Analyst",
                "team": "Analytics",
            },
        ]
    )
    service = TeamDirectoryService(directory_providers=[provider])

    emp, candidates, prompt = service.find_employee("Vijay")
    assert emp is None
    assert len(candidates) == 2
    assert prompt is not None
    assert "multiple people matching 'Vijay'" in prompt
    assert "Vijay Sharma" in prompt
    assert "Vijay Kumar" in prompt


def test_upcoming_holidays_and_leaves_differentiation():
    provider = InternalEmployeeDirectoryProvider()
    emp = provider.get_employee("EMP-004")  # Vijay Sharma
    assert emp is not None

    mock_cal_service = MagicMock()
    mock_cal_repo = MagicMock()
    mock_cal_service._repository = mock_cal_repo

    # Mock an organization holiday on the calendar
    holiday_entry = MagicMock()
    holiday_entry.entry_type = "holiday"
    holiday_entry.title = "Company Foundation Day"
    holiday_entry.start_time = datetime(2026, 11, 25, 0, 0, tzinfo=TeamDirectoryService.TIMEZONE)
    mock_cal_repo.find_entries.return_value = [holiday_entry]

    service = TeamDirectoryService(
        directory_providers=[provider],
        calendar_service=mock_cal_service,
    )

    items = service.get_upcoming_holidays_and_leaves(emp, days_ahead=30)
    assert len(items) >= 2
    # Verify approved personal leave is present and marked
    assert any("Approved Leave: Approved Leave on Nov 12 - Nov 13, 2026" in it for it in items)
    # Verify organization holiday is present and marked
    assert any("Public/Organization Holiday: Company Foundation Day" in it for it in items)



def test_answer_directory_query_standardized_format():
    service = TeamDirectoryService()

    answer = service.answer_directory_query("What is Hemant Kumar Sah's role, working hours and responsibilities?")

    # Verify standard sections
    assert "**Employee:** Hemant Kumar Sah" in answer
    assert "**Role:** Full Stack Engineer" in answer
    assert "**Working Hours:** 09:30 - 18:30 (Asia/Kolkata) [Monday, Tuesday, Wednesday, Thursday, Friday]" in answer
    assert "**Responsibilities:**" in answer
    assert "Workflow automations and webhook integrations" in answer
    assert "**Upcoming Holidays:**" in answer
    assert "**Source:** Internal Directory" in answer


def test_answer_responsibility_reverse_lookup():
    service = TeamDirectoryService()

    answer = service.answer_directory_query("Who is responsible for marketing automation?")
    assert "Hemant Kumar Sah" in answer
    assert "Full Stack Engineer" in answer
    assert "Marketing Automation" in answer or "Workflow automations" in answer
