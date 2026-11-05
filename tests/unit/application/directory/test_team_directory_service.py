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


def test_employee_lookup_ignores_trailing_question_mark():
    service = TeamDirectoryService()

    candidate = service._extract_name_candidate("Hemant?")
    assert candidate == "Hemant"

    answer = service.answer_directory_query("Hemant?")

    assert "Hemant Kumar Sah" in answer
    assert "couldn't find an employee" not in answer


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


def test_current_work_formats_extracted_items_without_internal_metadata():
    from application.person_work.person_work_service import (
        ExtractedWorkItem,
        WorkActivityType,
        PersonWorkSummary,
    )

    work_item = ExtractedWorkItem(
        work_item="Working on the IVAN video",
        activity_type=WorkActivityType.ACTIVE_WORK,
        status="in_progress",
        latest_update="Reached the Gemini usage limit",
        timestamp=datetime(2026, 11, 5, 10, 0),
        source_channel="D123456",
        source_ts="1234567890.123",
        person_id="U123456",
        person_name="Gurkirat Singh",
        evidence="Internal Slack evidence",
        confidence=0.95,
        project="IVAN",
    )

    summary = PersonWorkSummary(
        person_id="U123456",
        person_name="Gurkirat Singh",
        active_work=[work_item],
    )

    mock_person_work = MagicMock()
    mock_person_work.get_person_work_summary.return_value = summary

    service = TeamDirectoryService(person_work_service=mock_person_work)
    result = service.get_active_work_items(
        EmployeeProfile(
            employee_id="EMP-TEST",
            full_name="Gurkirat Singh",
            role="Operations Specialist",
            slack_user_id="U123456",
        )
    )

    assert result == [
        "Working on the IVAN video (In Progress; Project: IVAN)"
    ]

    rendered = " ".join(result)
    for internal_value in (
        "U123456",
        "1234567890.123",
        "Internal Slack evidence",
        "0.95",
        "ExtractedWorkItem",
        "ACTIVE_WORK",
    ):
        assert internal_value not in rendered
