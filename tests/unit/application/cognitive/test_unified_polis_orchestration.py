"""
Unit tests for Unified POLIS Orchestration across all three capabilities:
- Channel Monitor & DM Summariser
- HR & Team Directory Querying System
- Core Team Priority Tracker
- Combined Multi-Domain Requests & Discrepancy Reporting
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from application.cognitive.cognitive_planner import CognitivePlanner
from application.cognitive.simple_cognitive_engine import SimpleCognitiveEngine
from domain.reasoning.value_objects import ConversationContext, Question
from domain.reasoning.value_objects.request_plan import IntentCategory, TargetAgent


def _make_test_engine():
    pipeline = MagicMock()
    qa = MagicMock()
    qa.answer.return_value = MagicMock(text="QA fallback answer", confidence=0.8, evidence=[])

    planner = CognitivePlanner(llm_client=None)

    # Mock summarizer
    mock_summarizer = MagicMock()
    summary_result = MagicMock()
    summary_result.title = "Summary for #agentic-army"
    summary_result.formatted_text = "### 📋 Conversation Summary: #agentic-army\nKey discussion on IVAN and Twilio OTP."
    summary_result.delivered_privately = False
    mock_summarizer.execute_private_summary_workflow.return_value = summary_result

    # Mock directory service
    mock_directory = MagicMock()
    mock_directory.answer_directory_query.return_value = (
        "**Employee:** Hemant Kumar Sah\n\n"
        "**Role:** Full Stack Engineer\n\n"
        "**Working Hours:** 09:30 - 18:30 (Asia/Kolkata) [Monday, Tuesday, Wednesday, Thursday, Friday]\n\n"
        "**Responsibilities:** Workflow automations and webhook integrations\n\n"
        "**Upcoming Holidays:** Annual Leave on Nov 20 - Nov 21, 2026\n\n"
        "**Current Work:** Active in ownership areas: Marketing Automation\n\n"
        "**Source:** Internal Directory"
    )

    # Mock priority tracker
    mock_priority = MagicMock()
    mock_priority.answer_priority_query.return_value = (
        "**Highest Priority Team Task:** Core Team Hardening & Natural Organizational Intelligence\n\n"
        "**Status:** In Progress\n\n"
        "**Priority:** High\n\n"
        "**Owner:** Akshat Tripathi\n\n"
        "**Project / Sprint:** POLIS Core / Hardening Sprint\n\n"
        "**Deadline:** Nov 15, 2026\n\n"
        "**Reason for Ranking:** Overarching initiative in progress in active sprint (+115)\n\n"
        "**Source:** Jira (ID: INIT-1)"
    )

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        planner=planner,
        conversation_summarizer_service=mock_summarizer,
        team_directory_service=mock_directory,
        priority_ranking_service=mock_priority,
    )
    return engine, mock_summarizer, mock_directory, mock_priority


def test_orchestration_conversation_summary_request():
    engine, summarizer, _, _ = _make_test_engine()
    q = Question(text="Summarize today's discussion in #agentic-army.")

    plan = engine.planner.plan(q)
    assert plan.intent == IntentCategory.CONVERSATION_SUMMARY

    answer = engine.ask(q)
    assert "Conversation Summary: #agentic-army" in answer.text
    summarizer.execute_private_summary_workflow.assert_called_once()


def test_orchestration_hr_directory_query_request():
    engine, _, directory, _ = _make_test_engine()
    q = Question(text="What is Hemant Kumar Sah's role, working hours and responsibilities?")

    plan = engine.planner.plan(q)
    assert plan.intent == IntentCategory.HR_DIRECTORY_QUERY

    answer = engine.ask(q)
    assert "**Employee:** Hemant Kumar Sah" in answer.text
    assert "**Role:** Full Stack Engineer" in answer.text
    directory.answer_directory_query.assert_called_once()


def test_orchestration_priority_tracking_request():
    engine, _, _, priority = _make_test_engine()
    q = Question(text="What is our highest-priority team task currently in progress?")

    plan = engine.planner.plan(q)
    assert plan.intent == IntentCategory.PRIORITY_TRACKING_QUERY

    answer = engine.ask(q)
    assert "**Highest Priority Team Task:**" in answer.text
    assert "Core Team Hardening" in answer.text
    priority.answer_priority_query.assert_called_once()


def test_orchestration_combined_multi_domain_request():
    engine, _, directory, priority = _make_test_engine()

    q = Question(
        text="What is the latest update on backend migration, who owns it, and what is its current priority?"
    )

    plan = engine.planner.plan(q)
    assert plan.intent == IntentCategory.MULTI_AGENT_QUERY
    assert TargetAgent.CONVERSATION_SUMMARIZER in plan.required_agents
    assert TargetAgent.TEAM_DIRECTORY in plan.required_agents
    assert TargetAgent.PRIORITY_TRACKER in plan.required_agents

    answer = engine.ask(q)
    # Combined response synthesizes discussion, directory ownership, and priority
    assert "Recent Discussion & Updates" in answer.text or "Verified Ownership" in answer.text or "Project Priority" in answer.text
    directory.answer_directory_query.assert_called_once()
    priority.answer_priority_query.assert_called_once()


def test_orchestration_discrepancy_reporting():
    engine, _, _, _ = _make_test_engine()

    # Mock organizational conversation returning "completed"
    mock_org = MagicMock()
    mock_org.answer_question.return_value = MagicMock(text="In recent discussion, the team confirmed that backend migration is completed.")
    engine._organizational_conversation_service = mock_org

    # Mock priority tracker returning "in progress"
    mock_prio = MagicMock()
    mock_prio.answer_priority_query.return_value = "**Highest Priority Team Task:** Backend Migration\n**Status:** In Progress"
    engine._priority_ranking_service = mock_prio

    q = Question(text="What is the latest discussion, who owns it, and what is the priority?")
    plan = engine.planner.plan(q)

    answer = engine.ask(q)
    assert "Discrepancy Note" in answer.text
    assert "completed" in answer.text.lower()
    assert "in progress" in answer.text.lower()
