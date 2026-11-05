"""
Unit tests for Organizational Intelligence API routes:
- /conversations (history, summarize, send-summary)
- /employees (search, profile, schedule, holidays)
- /priorities (projects, sprints, ranked, highest-in-progress)
- Authentication (require_internal_api_key)
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException

from interfaces.api.dependencies import require_internal_api_key
from interfaces.api.routes.conversations import (
    ChannelHistoryRequest,
    ConversationSummarizeRequest,
    SendPrivateSummaryRequest,
    get_channel_history,
    send_private_summary,
    summarize_conversation,
)
from interfaces.api.routes.employees import (
    get_employee_holidays,
    get_employee_profile,
    get_employee_responsibilities,
    get_employee_schedule,
    search_employees,
)
from interfaces.api.routes.priorities import (
    get_highest_in_progress,
    get_projects,
    get_ranked_priorities,
    get_sprints,
    get_work_items,
)


def test_api_key_authentication(monkeypatch):
    from infrastructure.config.settings import get_settings
    monkeypatch.setattr(get_settings(), "polis_api_key", "secret-internal-key")

    # Valid key passes without exception
    require_internal_api_key(x_api_key="secret-internal-key")

    # Missing key raises 401
    with pytest.raises(HTTPException) as exc_info:
        require_internal_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401

    # Wrong key raises 401
    with pytest.raises(HTTPException) as exc_info:
        require_internal_api_key(x_api_key="wrong-key")
    assert exc_info.value.status_code == 401


def test_conversations_api_handlers():
    mock_summarizer = MagicMock()
    mock_summarizer.retrieve_channel_history.return_value = [
        {"user": "U1", "text": "Testing history", "ts": "100.0"}
    ]

    # 1. get_channel_history
    req = ChannelHistoryRequest(
        channel_id="C0BG7NWMD6D",
        requesting_user_id="U123",
        limit=10,
    )
    res = get_channel_history(request=req, summarizer_service=mock_summarizer)
    assert res["channel_id"] == "C0BG7NWMD6D"
    assert res["message_count"] == 1

    # 2. summarize_conversation
    mock_summary = MagicMock()
    mock_summary.title = "Summary for #agentic-army"
    mock_summary.discussion_points = ["Point 1"]
    mock_summary.confirmed_decisions = ["Decision 1"]
    mock_summary.suggestions = ["Idea 1"]
    mock_summary.action_items = [{"task": "Task 1", "owner": "Vijay"}]
    mock_summary.unresolved_questions = ["Question 1?"]
    mock_summary.participants = ["Vijay", "Akshat"]
    mock_summary.time_window = "today"
    mock_summary.source_channels = ["#agentic-army"]
    mock_summary.formatted_text = "Formatted summary text"
    mock_summarizer.execute_private_summary_workflow.return_value = mock_summary

    sum_req = ConversationSummarizeRequest(
        channel_id="C0BG7NWMD6D",
        requesting_user_id="U123",
        channel_name="#agentic-army",
    )
    sum_res = summarize_conversation(request=sum_req, summarizer_service=mock_summarizer)
    assert sum_res["title"] == "Summary for #agentic-army"
    assert len(sum_res["confirmed_decisions"]) == 1
    assert sum_res["action_items"][0]["owner"] == "Vijay"

    # 3. send_private_summary
    mock_summary.delivered_privately = True
    mock_summary.delivery_channel_id = "D12345"
    priv_req = SendPrivateSummaryRequest(
        channel_id="C0BG7NWMD6D",
        requesting_user_id="U123",
    )
    priv_res = send_private_summary(request=priv_req, summarizer_service=mock_summarizer)
    assert priv_res["status"] == "delivered"
    assert priv_res["delivered_privately"] is True
    assert priv_res["delivery_channel_id"] == "D12345"


def test_employees_api_handlers():
    mock_directory = MagicMock()
    mock_profile = MagicMock()
    mock_profile.employee_id = "EMP-001"
    mock_profile.full_name = "Akshat Tripathi"
    mock_profile.role = "AI Agent Implementor"
    mock_profile.department = "Engineering"
    mock_profile.team = "Core AI"
    mock_profile.reporting_manager = "Nav Thethi"
    mock_profile.working_hours = "09:30 - 18:30"
    mock_profile.working_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    mock_profile.time_zone = "Asia/Kolkata"
    mock_profile.responsibilities = ["Architecture", "Connectors"]
    mock_profile.skills = ["Python", "FastAPI"]
    mock_profile.areas_of_ownership = ["Core Engine"]
    mock_profile.email = "akshat@example.com"
    mock_profile.slack_user_id = "U0BB8T4BVEK"
    mock_profile.teams_user_id = "29:akshat"
    mock_profile.source = "Internal Directory"

    mock_directory.find_employee.return_value = (mock_profile, [mock_profile], None)
    mock_directory.get_upcoming_holidays_and_leaves.return_value = [
        "Approved Leave: Nov 12 - Nov 13, 2026"
    ]

    # 1. search_employees
    res_search = search_employees(q="Akshat", directory_service=mock_directory)
    assert res_search["status"] == "found"
    assert res_search["employee"]["full_name"] == "Akshat Tripathi"

    # 2. get_employee_profile
    res_prof = get_employee_profile(employee_id="EMP-001", directory_service=mock_directory)
    assert res_prof["role"] == "AI Agent Implementor"

    # 3. get_employee_schedule
    res_sched = get_employee_schedule(employee_id="EMP-001", directory_service=mock_directory)
    assert res_sched["working_hours"] == "09:30 - 18:30"

    # 4. get_employee_responsibilities
    res_resp = get_employee_responsibilities(employee_id="EMP-001", directory_service=mock_directory)
    assert "Architecture" in res_resp["responsibilities"]

    # 5. get_employee_holidays
    res_hol = get_employee_holidays(employee_id="EMP-001", days_ahead=30, directory_service=mock_directory)
    assert len(res_hol["upcoming_leaves_and_holidays"]) == 1


def test_priorities_api_handlers():
    mock_priority = MagicMock()

    mock_work_item = MagicMock()
    mock_work_item.item_id = "INIT-1"
    mock_work_item.title = "Core Team Hardening"
    mock_work_item.item_type = "initiative"
    mock_work_item.status = "in_progress"
    mock_work_item.priority = "high"
    mock_work_item.source_status = "In Progress"
    mock_work_item.source_priority = "High"
    mock_work_item.owner_name = "Akshat Tripathi"
    mock_work_item.owner_id = "U1"
    mock_work_item.project_name = "POLIS Core"
    mock_work_item.project_id = "PROJ-1"
    mock_work_item.sprint_name = "Hardening Sprint"
    mock_work_item.deadline = None
    mock_work_item.is_overarching = True
    mock_work_item.url = "https://linear.app/issue/1"
    mock_work_item.source_provider = "linear"

    mock_ranked = MagicMock()
    mock_ranked.item = mock_work_item
    mock_ranked.score = 115.0
    mock_ranked.reasons = ["Overarching in-progress task (+115)"]

    mock_priority.get_all_work_items.return_value = [mock_work_item]
    mock_priority.rank_work_items.return_value = [mock_ranked]
    mock_priority.get_highest_ranking_in_progress_task.return_value = mock_ranked
    mock_priority.answer_priority_query.return_value = "**Highest Priority Team Task:** Core Team Hardening"

    # 1. get_work_items
    res_items = get_work_items(status_filter=None, priority_service=mock_priority)
    assert res_items["item_count"] == 1

    # 2. get_ranked_priorities
    res_ranked = get_ranked_priorities(priority_service=mock_priority)
    assert res_ranked["item_count"] == 1
    assert res_ranked["ranked_items"][0]["title"] == "Core Team Hardening"

    # 3. get_highest_in_progress
    res_highest = get_highest_in_progress(priority_service=mock_priority)
    assert res_highest["highest_priority_item"]["title"] == "Core Team Hardening"
    assert "**Highest Priority Team Task:**" in res_highest["formatted_text"]
