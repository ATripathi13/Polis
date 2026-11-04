"""
Comprehensive regression tests for Employee Work Intelligence and Natural Response Generation.

Covers:
- Primary Scenario Case A: Gurkirat (podcast active work, Webinar 04 mention not active work, Kriss Miller reels conditional commitment).
- Primary Scenario Case B: Hemant (PolisBot capabilities consolidated into 1 workstream, break/sign-off omitted from work summary).
- Primary Scenario Case C: Vijay (work summary requests & mentions not technical deliverables, natural honest explanation).
- Additional Regression Requirements:
  1. Multiple related updates becoming one coherent workstream.
  2. Passing mentions not becoming confirmed active work.
  3. Administrative requests not becoming technical responsibilities.
  4. Explicit assignments remaining distinguishable from active work.
  5. Commitments remaining distinguishable from completed work.
  6. Completed work not appearing as ongoing work.
  7. Personal scheduling messages excluded from ordinary work summaries.
  8. Availability queries retaining relevant scheduling information.
  9. Missing evidence communicated naturally and honestly.
  10. No duplicate work appearing under multiple summary sections.
  11. Correct canonical employee ID preservation with multiple identifiers.
  12. Correct employee context in pronoun-based follow-up questions.
  13. LLM and deterministic fallback producing consistent classifications.
  14. Slack DM and channel responses using the same response-generation policy.
  15. No cross-employee attribution or accidental merging.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from application.cognitive import CognitivePlanner, SimpleCognitiveEngine
from application.person_work.person_work_service import (
    PersonWorkService,
    WorkActivityType,
)
from domain.common.identifier import Identifier
from domain.operations import InMemoryOperationalItemRepository
from domain.reasoning import Answer, Question
from domain.reasoning.value_objects.conversation_context import ConversationContext
from domain.reasoning.value_objects.request_plan import IntentCategory
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


def _build_comm(
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


class TestNaturalWorkIntelligence:

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
            {"id": "U_GURKIRAT", "name": "gurkirat", "real_name": "Gurkirat Singh", "profile": {"display_name": "Gurkirat"}},
            {"id": "U_HEMANT", "name": "hemant", "real_name": "Hemant Sharma", "profile": {"display_name": "Hemant"}},
            {"id": "U_VIJAY", "name": "vijay", "real_name": "Vijay Kumar", "profile": {"display_name": "Vijay"}},
            {"id": "U_AKSHAT", "name": "akshat", "real_name": "Akshat Tripathi", "profile": {"display_name": "Akshat"}},
            {"id": "U_COLLEAGUE", "name": "colleague", "real_name": "Colleague", "profile": {"display_name": "Colleague"}},
        ]
        service.get_workspace_users.return_value = users
        service.get_display_name.side_effect = lambda uid: next((u["profile"]["display_name"] for u in users if u["id"] == uid), uid)
        service.get_all_identifiers_for_user.side_effect = lambda uid: [uid, f"W_{uid}"]
        return service

    @pytest.fixture
    def work_service(self, comm_repo, ops_repo, mock_identity) -> PersonWorkService:
        return PersonWorkService(
            communication_repository=comm_repo,
            operational_item_repository=ops_repo,
            identity_service=mock_identity,
        )

    # -------------------------------------------------------------------------
    # Primary Scenario Case A — Gurkirat
    # -------------------------------------------------------------------------

    def test_case_a_gurkirat_podcast_webinar_reels(self, comm_repo, work_service):
        """
        Case A:
        - Preparing new podcast files for the CMO Blindspots episode. (reported active work)
        - A mention of extracting clips for Webinar 04. (passing mention, NOT active work)
        - A commitment to publish Kriss Miller reels once finalization is complete. (pending commitment)

        Expected:
        - Podcast preparation is actual reported active work.
        - Webinar 04 is NOT classified as Gurkirat's active work.
        - Reel publication is described as a pending conditional commitment, NOT completed.
        - Does not describe reels as completed without evidence.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm(
                "g1",
                "I am preparing new podcast files for the CMO Blindspots episode.",
                "U_GURKIRAT",
                "Gurkirat",
                created_at=now - timedelta(hours=3),
            )
        )
        comm_repo.save(
            _build_comm(
                "g2",
                "Someone mentioned extracting clips for Webinar 04, cc Gurkirat.",
                "U_COLLEAGUE",
                "Colleague",
                mentions=["U_GURKIRAT"],
                created_at=now - timedelta(hours=2),
            )
        )
        comm_repo.save(
            _build_comm(
                "g3",
                "I will publish Kriss Miller reels once finalization is complete.",
                "U_GURKIRAT",
                "Gurkirat",
                created_at=now - timedelta(hours=1),
            )
        )

        summary = work_service.get_person_work_summary(
            target_user_id="U_GURKIRAT",
            target_user_name="Gurkirat",
            query_text="What is Gurkirat working on?",
        )

        # 1. Active work: only CMO Blindspots podcast
        assert len(summary.active_work) == 1
        assert "CMO Blindspots" in summary.active_work[0].work_item or "podcast" in summary.active_work[0].work_item.lower()

        # 2. Passing mention Webinar 04 is NOT active work
        assert not any("webinar" in item.work_item.lower() for item in summary.active_work)
        assert any("webinar" in item.work_item.lower() for item in summary.discussions)

        # 3. Kriss Miller reels is a pending commitment, NOT completed work
        assert len(summary.commitments) == 1
        assert "reels" in summary.commitments[0].work_item.lower() or "kriss miller" in summary.commitments[0].work_item.lower()
        assert summary.commitments[0].activity_type == WorkActivityType.COMMITMENT
        assert summary.commitments[0].status == "planned"
        assert len(summary.completed_work) == 0

        # 4. Formatted response reflects this accurately
        resp = summary.formatted_response
        assert "**Current Work**" in resp
        assert "CMO Blindspots" in resp or "podcast" in resp.lower()
        assert "**Assigned Work and Commitments**" in resp
        assert "reels" in resp.lower()
        assert "**Recently Completed**" not in resp

    # -------------------------------------------------------------------------
    # Primary Scenario Case B — Hemant
    # -------------------------------------------------------------------------

    def test_case_b_hemant_chatbot_improvements_and_break_omitted(self, comm_repo, work_service):
        """
        Case B:
        - Improving PolisBot capabilities.
        - Updating its Knowledge Base.
        - Refining System Instructions.
        - Improving response behavior.
        - Testing recent changes.
        - Fixing response formatting.
        - Signing off and taking a break.

        Expected:
        - Present chatbot improvements as one coherent workstream.
        - Explain purpose in understandable language.
        - Mention testing and formatting as related progress.
        - Do not include sign-off and break information in ordinary work summary.
        - Do not claim completion beyond available evidence.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_comm("h1", "I am improving PolisBot capabilities.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=6)))
        comm_repo.save(_build_comm("h2", "I updated the Knowledge Base.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=5)))
        comm_repo.save(_build_comm("h3", "I am refining the System Instructions.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=4)))
        comm_repo.save(_build_comm("h4", "I'm improving response behavior.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=3)))
        comm_repo.save(_build_comm("h5", "Testing recent changes and fixing response formatting.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=2)))
        comm_repo.save(_build_comm("h6", "Signing off and taking a break.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=1)))

        summary = work_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            query_text="What is Hemant currently working on?",
        )

        # 1. Chatbot improvements consolidated into ONE workstream
        assert len(summary.active_work) == 1
        ws = summary.active_work[0]
        assert "PolisBot" in ws.work_item or "response" in ws.work_item.lower()

        # 2. Progress updates captured in history
        assert len(ws.updates) >= 4

        # 3. Personal scheduling message 'Signing off and taking a break' completely excluded
        resp = summary.formatted_response.lower()
        assert "signing off" not in resp
        assert "taking a break" not in resp
        assert not any("signing off" in item.work_item.lower() for item in summary.items)

        # 4. Workstream is active (not falsely claimed 100% completed)
        assert ws.activity_type == WorkActivityType.ACTIVE_WORK
        assert len(summary.completed_work) == 0

    # -------------------------------------------------------------------------
    # Primary Scenario Case C — Vijay
    # -------------------------------------------------------------------------

    def test_case_c_vijay_work_summary_and_circle_mentions(self, comm_repo, work_service):
        """
        Case C:
        - Discussions about providing a work summary.
        - References to GJ and Circle.
        - A request or expectation for Vijay to provide an update.

        Expected:
        - Do not report work-summary request as ongoing technical project.
        - Do not invent responsibilities involving GJ or Circle.
        - Do not interpret mentions as proof of ownership.
        - Explain that available discussions do not establish a specific ongoing deliverable.
        - Keep response concise and honest.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm(
                "v1",
                "Vijay, please provide your work summary.",
                "U_COLLEAGUE",
                "Colleague",
                mentions=["U_VIJAY"],
                created_at=now - timedelta(hours=3),
            )
        )
        comm_repo.save(
            _build_comm(
                "v2",
                "GJ and Circle were mentioned in the sync with Vijay.",
                "U_COLLEAGUE",
                "Colleague",
                mentions=["U_VIJAY"],
                created_at=now - timedelta(hours=2),
            )
        )
        comm_repo.save(
            _build_comm(
                "v3",
                "We need Vijay to share an update on Circle.",
                "U_COLLEAGUE",
                "Colleague",
                mentions=["U_VIJAY"],
                created_at=now - timedelta(hours=1),
            )
        )

        summary = work_service.get_person_work_summary(
            target_user_id="U_VIJAY",
            target_user_name="Vijay",
            query_text="What is Vijay working on?",
        )

        # 1. No active technical work or assigned technical deliverables invented
        assert len(summary.active_work) == 0
        assert len(summary.assigned_work) == 0
        assert len(summary.commitments) == 0
        assert len(summary.completed_work) == 0

        # 2. Discussions recorded as discussions only
        assert len(summary.discussions) >= 1

        # 3. Honest, natural collegial explanation
        resp = summary.formatted_response
        assert "not establish a specific ongoing deliverable" in resp.lower() or "not establish" in resp.lower()
        assert "Vijay" in resp
        assert "Current Work" not in resp

    # -------------------------------------------------------------------------
    # Additional Regression Tests
    # -------------------------------------------------------------------------

    def test_availability_query_retains_scheduling_information(self, comm_repo, work_service):
        """
        Requirement 8: Query-aware handling retains scheduling information when asked.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_comm("h_off", "Signing off and taking a break for the day.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=1)))

        # Availability query retains the notice
        summary_avail = work_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            query_text="When did Hemant sign off? Is Hemant available?",
        )
        assert summary_avail.query_focus == "availability"
        assert "signing off" in summary_avail.formatted_response.lower()

        # Ordinary work query excludes the notice
        summary_work = work_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            query_text="What is Hemant currently working on?",
        )
        assert "signing off" not in summary_work.formatted_response.lower()

    def test_administrative_requests_do_not_become_technical_responsibilities(self, comm_repo, work_service):
        """
        Requirement 3: 'Vijay, please provide your work summary' does not become assigned technical work.
        """
        comm_repo.save(_build_comm("adm1", "Vijay, please provide your work summary.", "U_COLLEAGUE", "Colleague", mentions=["U_VIJAY"]))
        comm_repo.save(_build_comm("adm2", "Vijay, please share an update.", "U_COLLEAGUE", "Colleague", mentions=["U_VIJAY"]))

        summary = work_service.get_person_work_summary(target_user_id="U_VIJAY", target_user_name="Vijay")
        assert len(summary.assigned_work) == 0
        assert len(summary.active_work) == 0

    def test_explicit_assignments_remain_distinguishable_from_active_work(self, comm_repo, work_service):
        """
        Requirement 4: Explicit deliverable assigned to employee is ASSIGNED_WORK, not ACTIVE_WORK.
        """
        comm_repo.save(_build_comm("asg1", "Hemant, please implement the OAuth2 token refresh endpoint.", "U_COLLEAGUE", "Colleague", mentions=["U_HEMANT"]))

        summary = work_service.get_person_work_summary(target_user_id="U_HEMANT", target_user_name="Hemant")
        assert len(summary.assigned_work) == 1
        assert "OAuth2" in summary.assigned_work[0].work_item
        assert summary.assigned_work[0].activity_type == WorkActivityType.ASSIGNED_WORK
        assert len(summary.active_work) == 0

    def test_commitments_remain_distinguishable_from_completed_work(self, comm_repo, work_service):
        """
        Requirement 5: Commitments are marked as planned/upcoming, never as completed work.
        """
        comm_repo.save(_build_comm("cmt1", "I will publish Kriss Miller reels once finalization is complete.", "U_GURKIRAT", "Gurkirat"))

        summary = work_service.get_person_work_summary(target_user_id="U_GURKIRAT", target_user_name="Gurkirat")
        assert len(summary.commitments) == 1
        assert summary.commitments[0].activity_type == WorkActivityType.COMMITMENT
        assert summary.commitments[0].status == "planned"
        assert len(summary.completed_work) == 0

    def test_completed_work_does_not_appear_as_ongoing_work(self, comm_repo, work_service):
        """
        Requirement 6: Completed work goes to completed_work, not active_work.
        """
        comm_repo.save(_build_comm("cmp1", "The Slack ingestion changes are complete.", "U_AKSHAT", "Akshat"))

        summary = work_service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        assert len(summary.completed_work) == 1
        assert len(summary.active_work) == 0

    def test_no_duplicate_work_under_multiple_sections(self, comm_repo, work_service):
        """
        Requirement 10: Deterministic fallback does not clone current work into Overall Priorities.
        """
        comm_repo.save(_build_comm("act1", "I am implementing the Organizational Event Engine.", "U_AKSHAT", "Akshat"))

        summary = work_service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        resp = summary.formatted_response

        # Current Work is present
        assert "**Current Work**" in resp
        # Redundant duplicate Overall Priorities repeating current work is absent
        assert "**Overall Priorities**" not in resp

    def test_no_cross_employee_attribution_or_accidental_merging(self, comm_repo, work_service):
        """
        Requirement 15: Separate employees' updates are never merged, even if sharing generic words like 'testing' and 'api'.
        """
        comm_repo.save(_build_comm("m_akshat", "Testing user login API.", "U_AKSHAT", "Akshat"))
        comm_repo.save(_build_comm("m_hemant", "Testing IVAN integration API.", "U_HEMANT", "Hemant"))

        sum_akshat = work_service.get_person_work_summary(target_user_id="U_AKSHAT", target_user_name="Akshat")
        sum_hemant = work_service.get_person_work_summary(target_user_id="U_HEMANT", target_user_name="Hemant")

        assert len(sum_akshat.items) == 1
        assert sum_akshat.items[0].person_id == "U_AKSHAT"
        assert "login" in sum_akshat.items[0].work_item.lower()

        assert len(sum_hemant.items) == 1
        assert sum_hemant.items[0].person_id == "U_HEMANT"
        assert "ivan" in sum_hemant.items[0].work_item.lower()

    def test_llm_prompt_evidence_and_instructions_alignment(self, comm_repo, mock_identity):
        """
        Requirement 13: The LLM prompt receives synthesized, accurately partitioned evidence
        and humanized collegial synthesis instructions without rigid boilerplate mandates.
        """
        captured_prompt = []

        class MockLLM:
            def generate(self, prompt: str) -> str:
                captured_prompt.append(prompt)
                return "Gurkirat is preparing the CMO Blindspots podcast."

        service = PersonWorkService(
            communication_repository=comm_repo,
            identity_service=mock_identity,
            llm_client=MockLLM(),
        )

        now = datetime.now(timezone.utc)
        comm_repo.save(_build_comm("p1", "I am preparing new podcast files for the CMO Blindspots episode.", "U_GURKIRAT", "Gurkirat", created_at=now - timedelta(hours=2)))
        comm_repo.save(_build_comm("p2", "I will publish Kriss Miller reels once finalization is complete.", "U_GURKIRAT", "Gurkirat", created_at=now - timedelta(hours=1)))

        summary = service.get_person_work_summary(
            target_user_id="U_GURKIRAT",
            target_user_name="Gurkirat",
            query_text="What is Gurkirat working on?",
        )

        assert len(captured_prompt) == 1
        prompt_text = captured_prompt[0]
        # Instructions emphasize collegial synthesis
        assert "knowledgeable, human colleague" in prompt_text
        assert "Synthesize before communicating" in prompt_text
        assert "Active Work & Workstreams" in prompt_text
        assert "Upcoming Commitments" in prompt_text
        # Does not force rigid 5-section boilerplate
        assert "Do NOT force a rigid 5-section template" in prompt_text

    @pytest.fixture
    def engine(self, comm_repo, ops_repo, mock_identity, work_service) -> SimpleCognitiveEngine:
        qa_service = MagicMock()
        qa_service.answer.return_value = Answer(text="Generic fallback.", confidence=0.5)
        pipeline = MagicMock()
        planner = CognitivePlanner(identity_service=mock_identity)

        return SimpleCognitiveEngine(
            pipeline=pipeline,
            question_answering=qa_service,
            planner=planner,
            operational_item_repository=ops_repo,
            identity_resolver=mock_identity,
            person_work_service=work_service,
        )

    def test_canonical_employee_id_preservation_with_multiple_identifiers(self, comm_repo, work_service):
        """
        Requirement 11: Multi-identifier mapping correctly retrieves records and preserves canonical person ID.
        """
        now = datetime.now(timezone.utc)
        # Authored using secondary identifier W_U_AKSHAT
        comm_repo.save(_build_comm("id1", "I am implementing the Organizational Event Engine.", "W_U_AKSHAT", "Akshat", created_at=now - timedelta(hours=1)))

        summary = work_service.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
        )

        assert len(summary.active_work) == 1
        assert summary.active_work[0].person_id == "U_AKSHAT"

    def test_slack_dm_and_channel_response_consistency(self, engine, comm_repo):
        """
        Requirement 14: DM and public channel queries by authorized users produce
        consistent work intelligence classifications.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_comm("pub1", "I am preparing new podcast files for the CMO Blindspots episode.", "U_GURKIRAT", "Gurkirat", channel_id="C_PUB", channel_type="public", created_at=now - timedelta(hours=2)))
        comm_repo.save(_build_comm("pub2", "I will publish Kriss Miller reels once finalization is complete.", "U_GURKIRAT", "Gurkirat", channel_id="C_PUB", channel_type="public", created_at=now - timedelta(hours=1)))

        # 1. Ask in Public Channel
        ctx_pub = ConversationContext(user_id="U_AKSHAT", channel_id="C_PUB", thread_ts="", channel_type="public")
        q_pub = Question(text="What is Gurkirat working on?", context=ctx_pub, user_id="U_AKSHAT")
        ans_pub = engine.ask(q_pub)

        # 2. Ask in DM
        ctx_dm = ConversationContext(user_id="U_AKSHAT", channel_id="D_AKSHAT", thread_ts="", channel_type="im")
        q_dm = Question(text="What is Gurkirat working on?", context=ctx_dm, user_id="U_AKSHAT")
        ans_dm = engine.ask(q_dm)

        assert ans_pub is not None and ans_dm is not None
        assert "CMO Blindspots" in ans_pub.text or "podcast" in ans_pub.text.lower()
        assert "CMO Blindspots" in ans_dm.text or "podcast" in ans_dm.text.lower()
        assert "reels" in ans_pub.text.lower()
        assert "reels" in ans_dm.text.lower()

    def test_pronoun_continuity_in_follow_up_work_queries(self, engine, comm_repo):
        """
        Requirement 12: Correct employee context in pronoun-based follow-up questions ('What has he completed?').
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_comm("h1", "I am improving PolisBot capabilities.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=3)))
        comm_repo.save(_build_comm("h2", "The API integration is complete.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=1)))

        ctx = ConversationContext(user_id="U_AKSHAT", channel_id="D_AKSHAT", thread_ts="", channel_type="im")

        # Turn 1: Explicit name
        q1 = Question(text="What is Hemant working on?", context=ctx, user_id="U_AKSHAT")
        ans1 = engine.ask(q1)
        assert ans1 is not None
        assert "PolisBot" in ans1.text or "response" in ans1.text.lower()

        # Update context exchange
        ctx = ctx.add_exchange(
            user_message="What is Hemant working on?",
            assistant_message=ans1.text,
            user_id="U_AKSHAT",
            user_metadata={"target_user_id": "U_HEMANT", "target_user_name": "Hemant"},
            assistant_metadata={"target_user_id": "U_HEMANT", "target_user_name": "Hemant"},
        )

        # Turn 2: Pronoun 'he'
        q2 = Question(text="What has he completed?", context=ctx, user_id="U_AKSHAT")
        ans2 = engine.ask(q2)
        assert ans2 is not None
        assert "**Recently Completed**" in ans2.text
        assert "API integration" in ans2.text

    def test_polisbot_is_not_merged_into_polis_production_deployment(self, work_service):
        """PolisBot work and POLIS production deployment are separate workstreams."""
        from application.person_work.person_work_service import ExtractedWorkItem

        now = datetime.now(timezone.utc)

        items = [
            ExtractedWorkItem(
                work_item="Improving Polis Bot response quality",
                activity_type=WorkActivityType.ACTIVE_WORK,
                status="in_progress",
                latest_update="Refining Polis Bot response quality",
                timestamp=now - timedelta(hours=2),
                source_channel="engineering",
                source_ts="1",
                person_id="U_HEMANT",
                person_name="Hemant",
                evidence="Direct employee update",
            ),
            ExtractedWorkItem(
                work_item="Deploying POLIS API to production",
                activity_type=WorkActivityType.ACTIVE_WORK,
                status="in_progress",
                latest_update="Deploying POLIS API to production",
                timestamp=now - timedelta(hours=1),
                source_channel="engineering",
                source_ts="2",
                person_id="U_HEMANT",
                person_name="Hemant",
                evidence="Direct employee update",
            ),
        ]

        result = work_service._consolidate_and_rank(items)

        assert len(result) == 2
        assert any("bot" in item.work_item.lower() for item in result)
        assert any("production" in item.work_item.lower() for item in result)

    def test_generic_progress_does_not_merge_unrelated_workstreams(self, work_service):
        """Generic testing updates must not attach to an unrelated active project."""
        from application.person_work.person_work_service import ExtractedWorkItem

        now = datetime.now(timezone.utc)

        items = [
            ExtractedWorkItem(
                work_item="Canva graphics generation",
                activity_type=WorkActivityType.ACTIVE_WORK,
                status="in_progress",
                latest_update="Creating Canva graphics",
                timestamp=now - timedelta(hours=2),
                source_channel="marketing",
                source_ts="1",
                person_id="U_HEMANT",
                person_name="Hemant",
                evidence="Direct employee update",
            ),
            ExtractedWorkItem(
                work_item="Testing recent changes for IVAN integration",
                activity_type=WorkActivityType.ACTIVE_WORK,
                status="in_progress",
                latest_update="Testing recent changes for IVAN integration",
                timestamp=now - timedelta(hours=1),
                source_channel="engineering",
                source_ts="2",
                person_id="U_HEMANT",
                person_name="Hemant",
                evidence="Direct employee update",
            ),
        ]

        result = work_service._consolidate_and_rank(items)

        assert len(result) == 2
        assert any("canva" in item.work_item.lower() for item in result)
        assert any("ivan" in item.work_item.lower() for item in result)