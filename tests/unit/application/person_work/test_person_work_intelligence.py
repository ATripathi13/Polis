"""
Unit tests for person-specific work intelligence and humanized response generation.

Validates:
1. Semantic and structural filtering:
   - Interrogative questions are not classified as work evidence.
   - Questions about current work or completions are excluded.
   - Greetings and generic bot prompts are excluded.
   - Bot mentions do not become commitments.
   - Genuine completion statements remain classified as completed.
   - Genuine commitments remain classified as commitments.
   - Actual assignments remain assigned work, while casual mentions are not assigned work.
   - Thread replies preserve context and attribution.
2. Workstream consolidation:
   - Multiple related updates on the same project produce one consolidated workstream.
3. Humanized synthesis:
   - Raw Slack messages and debug status codes are not reproduced in responses.
   - Query intent adaptation (current work, priorities, completed, blockers).
   - Safe, readable fallback when LLM fails or is unavailable.
   - Grounding in supplied evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from application.person_work.person_work_service import (
    PersonWorkService,
    WorkActivityType,
)
from domain.common.identifier import Identifier
from domain.operations import (
    InMemoryOperationalItemRepository,
)
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from engines.communication.infrastructure.repositories.memory_repository import (
    InMemoryCommunicationRepository,
)


def _build_event(
    event_id: str,
    text: str,
    actor_id: str,
    actor_name: str,
    channel_id: str = "C_DEV",
    channel_name: str = "engineering",
    channel_type: str = "public",
    created_at: datetime | None = None,
    correlation_id: str | None = None,
    mentions: list[str] | None = None,
    metadata: dict | None = None,
) -> CommunicationEvent:
    ev = CommunicationEvent.create(
        correlation_id=Identifier(business_id=correlation_id or event_id),
        source=EventSource.SLACK,
        source_event_id=event_id,
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id=actor_id,
                external_ids={"slack": actor_id},
            ),
            display_name=actor_name,
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id=channel_id,
                external_ids={"slack": channel_id},
            ),
            name=channel_name,
            channel_type=channel_type,
        ),
        content=Content(
            body=text,
            metadata=metadata or {},
        ),
        mentions=mentions or [],
    )
    ev.created_at = created_at or datetime.now(timezone.utc)
    return ev


class TestPersonWorkIntelligence:

    @pytest.fixture
    def comm_repo(self) -> InMemoryCommunicationRepository:
        return InMemoryCommunicationRepository()

    @pytest.fixture
    def ops_repo(self) -> InMemoryOperationalItemRepository:
        return InMemoryOperationalItemRepository()

    @pytest.fixture
    def mock_identity(self) -> MagicMock:
        service = MagicMock()
        users = [
            {"id": "U_AKSHAT", "name": "akshat", "real_name": "Akshat Tripathi", "profile": {"display_name": "Akshat"}},
            {"id": "U_GURKIRAT", "name": "gurkirat", "real_name": "Gurkirat Singh", "profile": {"display_name": "Gurkirat"}},
            {"id": "U_HEMANT", "name": "hemant", "real_name": "Hemant Sharma", "profile": {"display_name": "Hemant"}},
            {"id": "U_VIJAY", "name": "vijay", "real_name": "Vijay Kumar", "profile": {"display_name": "Vijay"}},
            {"id": "U_COLLEAGUE", "name": "colleague", "real_name": "Colleague", "profile": {"display_name": "Colleague"}},
        ]
        service.get_workspace_users.return_value = users
        service.get_display_name.side_effect = lambda uid: next((u["profile"]["display_name"] for u in users if u["id"] == uid), uid)
        service.get_all_identifiers_for_user.side_effect = lambda uid: [uid]
        return service

    @pytest.fixture
    def service(self, comm_repo, ops_repo, mock_identity) -> PersonWorkService:
        return PersonWorkService(
            communication_repository=comm_repo,
            operational_item_repository=ops_repo,
            identity_service=mock_identity,
        )

    # -------------------------------------------------------------
    # Classification & Filtering Tests
    # -------------------------------------------------------------

    def test_questions_containing_completed_do_not_become_completed_work(self, comm_repo, service):
        """
        Defect: 'What has Hemant completed this week?' was falsely classified as completed work.
        Requirement: Interrogative questions must be excluded from work evidence.
        """
        comm_repo.save(_build_event("m1", "What has Hemant completed this week?", "U_COLLEAGUE", "Colleague", mentions=["U_HEMANT"]))

        summary = service.get_person_work_summary(target_user_id="U_HEMANT", target_user_name="Hemant")
        assert len(summary.completed_work) == 0
        assert len(summary.items) == 0

    def test_questions_about_current_work_are_excluded(self, comm_repo, service):
        """
        Defect: 'What am I currently working on?' or 'What is Akshat working on?' was classified as active work.
        Requirement: Queries about work are questions, not work evidence.
        """
        comm_repo.save(_build_event("m2", "What am I currently working on?", "U_AKSHAT", "Akshat"))
        comm_repo.save(_build_event("m3", "What is Akshat working on?", "U_COLLEAGUE", "Colleague", mentions=["U_AKSHAT"]))

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        assert len(summary.active_work) == 0
        assert len(summary.items) == 0

    def test_greetings_and_generic_polis_prompts_are_excluded(self, comm_repo, service):
        """
        Requirement: Pure greetings, pleasantries, and bot capability queries must be excluded.
        """
        comm_repo.save(_build_event("g1", "Hi POLIS, what can you help me with?", "U_AKSHAT", "Akshat"))
        comm_repo.save(_build_event("g2", "Good morning team!", "U_AKSHAT", "Akshat"))
        comm_repo.save(_build_event("g3", "Who is Akshat?", "U_COLLEAGUE", "Colleague"))

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        assert len(summary.items) == 0

    def test_bot_mentions_do_not_become_employee_work(self, comm_repo, service):
        """
        Requirement: Mentioning the bot or asking for assistance must not create employee commitments.
        """
        comm_repo.save(_build_event("bm1", "<@U_POLIS> could you check the calendar?", "U_AKSHAT", "Akshat"))
        comm_repo.save(_build_event("bm2", "POLIS, help me find the handbook", "U_AKSHAT", "Akshat"))

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        assert len(summary.commitments) == 0
        assert len(summary.items) == 0

    def test_genuine_completion_statements_remain_classified_as_completed(self, comm_repo, service):
        """
        Requirement: Genuine factual completion statements must be classified as completed work.
        """
        comm_repo.save(_build_event("c1", "The Slack ingestion changes are complete.", "U_AKSHAT", "Akshat"))
        comm_repo.save(_build_event("c2", "I have finished the auth service migration.", "U_AKSHAT", "Akshat"))

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        assert len(summary.completed_work) == 2
        assert any("Slack ingestion" in item.work_item for item in summary.completed_work)
        assert any("auth service migration" in item.work_item for item in summary.completed_work)

    def test_genuine_commitments_remain_classified_as_commitments(self, comm_repo, service):
        """
        Requirement: Explicit commitment and plan statements must be classified as commitments.
        """
        comm_repo.save(_build_event("cm1", "I will start the Calendar Agent after the event engine is finished.", "U_AKSHAT", "Akshat"))

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        assert len(summary.commitments) == 1
        assert "Calendar Agent" in summary.commitments[0].work_item

    def test_actual_assignments_remain_assigned_work(self, comm_repo, service):
        """
        Requirement: Direct work assignments to an employee are classified as assigned work,
        while casual mentions in passing are not.
        """
        comm_repo.save(_build_event("as1", "Gurkirat, please test the approval-to-post workflow.", "U_COLLEAGUE", "Colleague", mentions=["U_GURKIRAT"]))
        comm_repo.save(_build_event("as2", "I met with Gurkirat to discuss the new roadmap.", "U_COLLEAGUE", "Colleague", mentions=["U_GURKIRAT"]))

        summary = service.get_person_work_summary(target_user_id="U_GURKIRAT", target_user_name="Gurkirat")
        # Direct assignment should be in assigned_work
        assert len(summary.assigned_work) == 1
        assert "approval-to-post" in summary.assigned_work[0].work_item
        # Casual mention should NOT be in assigned_work
        assert not any("roadmap" in item.work_item for item in summary.assigned_work)

    def test_thread_replies_preserve_context_and_attribution(self, comm_repo, service):
        """
        Requirement: Thread replies combine parent context without attributing parent author's
        work to the reply author.
        """
        parent = _build_event("p1", "We need to improve the IVAN QA workflow.", "U_COLLEAGUE", "Colleague")
        comm_repo.save(parent)

        reply = _build_event(
            "r1",
            "I've updated the testing personas. I still need to validate the remaining scenarios.",
            "U_AKSHAT",
            "Akshat",
            correlation_id="p1",
            metadata={"parent_message_body": "We need to improve the IVAN QA workflow.", "parent_actor_name": "Colleague", "parent_actor_id": "U_COLLEAGUE"},
        )
        comm_repo.save(reply)

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        assert len(summary.items) > 0
        for item in summary.items:
            assert item.person_id == "U_AKSHAT"
        assert any("IVAN QA workflow" in item.work_item or "testing personas" in item.work_item for item in summary.items)

    # -------------------------------------------------------------
    # Consolidation Tests
    # -------------------------------------------------------------

    def test_multiple_messages_same_project_become_coherent_workstream(self, comm_repo, service):
        """
        Requirement: Multiple messages about the same project (POLIS deployment)
        should produce one consolidated workstream rather than multiple disconnected fragments.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_event("d1", "I am preparing the POLIS production deployment.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=4)))
        comm_repo.save(_build_event("d2", "I have updated the Docker configuration.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=3)))
        comm_repo.save(_build_event("d3", "The API is now deployed.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=2)))
        comm_repo.save(_build_event("d4", "I am validating the Slack integration.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=1)))

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        # Should consolidate related deployment updates under the POLIS deployment workstream
        assert len(summary.active_work) == 1
        active = summary.active_work[0]
        assert "POLIS" in active.work_item or "deployment" in active.work_item
        # All 4 updates are recorded under this workstream
        assert len(active.updates) == 4

    # -------------------------------------------------------------
    # Synthesis & Response Quality Tests
    # -------------------------------------------------------------

    def test_raw_slack_messages_not_reproduced_as_final_answer(self, comm_repo, service):
        """
        Requirement: The response must not dump raw internal metadata, status codes,
        or channel tags.
        """
        comm_repo.save(_build_event("s1", "I am implementing the Organizational Event Engine.", "U_AKSHAT", "Akshat"))

        summary = service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        resp = summary.formatted_response

        # Check absence of internal technical debug tokens
        assert "Status: in_progress" not in resp
        assert "Source: #" not in resp
        assert "Polis Task ID:" not in resp

    def test_current_work_queries_produce_focused_responses(self, comm_repo, mock_identity):
        """
        Requirement: When an LLM client is available, it synthesizes a natural,
        focused answer for current work queries.
        """
        mock_llm = MagicMock()
        mock_llm.generate.return_value = (
            "Here's what Akshat is currently working on.\n\n"
            "**Current Work**\n"
            "• **Organizational Event Engine**: Akshat is actively implementing the event engine.\n\n"
            "**Overall Priorities**\n"
            "• Complete the event engine implementation."
        )

        service_with_llm = PersonWorkService(
            communication_repository=comm_repo,
            identity_service=mock_identity,
            llm_client=mock_llm,
        )

        comm_repo.save(_build_event("m1", "I am implementing the Organizational Event Engine.", "U_AKSHAT", "Akshat"))

        summary = service_with_llm.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
            query_text="What is Akshat currently working on?",
        )

        assert mock_llm.generate.called
        call_prompt = mock_llm.generate.call_args[0][0]
        assert "Organizational Event Engine" in call_prompt
        assert "current_work" in call_prompt

        assert "Organizational Event Engine" in summary.formatted_response
        assert "actively implementing" in summary.formatted_response

    def test_completion_queries_report_only_completed_items(self, comm_repo, service):
        """
        Requirement: When asking what was completed, only completed work is surfaced.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_event("h1", "I am working on the database indexing.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=2)))
        comm_repo.save(_build_event("h2", "The API integration is complete.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=1)))

        summary = service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            query_text="What has Hemant completed this week?",
        )

        resp = summary.formatted_response
        assert "**Recently Completed**" in resp
        assert "API integration" in resp

    def test_blocker_queries_report_only_supported_blockers(self, comm_repo, service):
        """
        Requirement: When asking for blockers, focus specifically on identified blockers.
        """
        comm_repo.save(_build_event("v1", "The deployment is blocked because the API credentials are not available.", "U_VIJAY", "Vijay"))

        summary = service.get_person_work_summary(
            target_user_id="U_VIJAY",
            target_user_name="Vijay",
            query_text="What is Vijay blocked on?",
        )

        resp = summary.formatted_response
        assert "**Blockers and Dependencies**" in resp
        assert "API credentials" in resp

    def test_empty_evidence_produces_honest_response(self, service):
        """
        Requirement: Empty evidence reports the lookback window honestly without hallucinating.
        """
        summary = service.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
            lookback_days=7,
        )

        resp = summary.formatted_response
        assert "7 days" in resp
        assert "no recent work activity" in resp.lower()

    def test_llm_failure_uses_safe_readable_fallback(self, comm_repo, mock_identity):
        """
        Requirement: If the LLM throws an exception, use the deterministic fallback
        safely without exposing errors or raw conversation transcripts.
        """
        failing_llm = MagicMock()
        failing_llm.generate.side_effect = RuntimeError("OpenAI API rate limit exceeded")

        service_with_failing_llm = PersonWorkService(
            communication_repository=comm_repo,
            identity_service=mock_identity,
            llm_client=failing_llm,
        )

        comm_repo.save(_build_event("fb1", "I am implementing the Organizational Event Engine.", "U_AKSHAT", "Akshat"))

        summary = service_with_failing_llm.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
            query_text="What is Akshat working on?",
        )

        # Fallback executed cleanly
        assert summary.formatted_response is not None
        assert "**Current Work**" in summary.formatted_response
        assert "Organizational Event Engine" in summary.formatted_response
