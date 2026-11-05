"""
Unit tests for Natural, Context-Aware, and Consistent Responses in Slack DMs and Channels.

Validates Acceptance Criteria:
1. Complete context & connected workstreams:
   - Multi-person problem -> solution -> confirmation messages connected into 1 workstream.
   - Questions and mentions are never mistaken for proof of work.
2. Natural, humanized collegial responses:
   - Specific intent adaptation (current work, completed, pending, blockers, assigned).
   - Missing or unverified completion communicated honestly and conversationally.
3. Conversational continuity:
   - Follow-up questions with pronouns ('What has he completed?', 'What is still pending?')
     correctly resolve the antecedent employee across turns.
4. Privacy & Authorization boundaries:
   - Private channel / DM records are never leaked to public channel queries.
   - Unauthorized users cannot access private messages.
   - Authorized participants receive consistent reasoning across DMs and channels.
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
from application.pipeline.pipeline import PolisPipeline
from domain.common.identifier import Identifier
from domain.operations import InMemoryOperationalItemRepository
from domain.reasoning import (
    Answer,
    Question,
    QuestionAnsweringService,
)
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


class TestContextAwareContinuity:

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
            {"id": "U_HEMANT", "name": "hemant", "real_name": "Hemant Sharma", "profile": {"display_name": "Hemant"}},
            {"id": "U_VIJAY", "name": "vijay", "real_name": "Vijay Kumar", "profile": {"display_name": "Vijay"}},
            {"id": "U_ALEX", "name": "alex", "real_name": "Alex Tech", "profile": {"display_name": "Alex"}},
        ]
        service.get_workspace_users.return_value = users
        service.get_display_name.side_effect = lambda uid: next((u["profile"]["display_name"] for u in users if u["id"] == uid), uid)
        service.get_all_identifiers_for_user.side_effect = lambda uid: [uid]
        return service

    @pytest.fixture
    def person_service(self, comm_repo, ops_repo, mock_identity) -> PersonWorkService:
        return PersonWorkService(
            communication_repository=comm_repo,
            operational_item_repository=ops_repo,
            identity_service=mock_identity,
        )

    @pytest.fixture
    def engine(self, comm_repo, ops_repo, mock_identity, person_service) -> SimpleCognitiveEngine:
        qa_service = MagicMock(spec=QuestionAnsweringService)
        qa_service.answer.return_value = Answer(text="Generic fallback.", confidence=0.5)
        pipeline = MagicMock(spec=PolisPipeline)
        planner = CognitivePlanner(identity_service=mock_identity)

        return SimpleCognitiveEngine(
            pipeline=pipeline,
            question_answering=qa_service,
            planner=planner,
            operational_item_repository=ops_repo,
            identity_resolver=mock_identity,
            person_work_service=person_service,
        )

    # -------------------------------------------------------------------------
    # 1. Multi-person Workstream Connection: Problem -> Solution -> Confirmation
    # -------------------------------------------------------------------------

    def test_multi_person_problem_solution_confirmation_combined(self, comm_repo, person_service):
        """
        Lead discusses a problem: 'The email OTP verification flow is timing out in production.'
        Colleague assigns fix: 'Hemant, please fix the email OTP verification timeout bug.'
        Hemant confirms implementation: 'I have fixed the email OTP timeout bug and verified the verification flow in staging.'

        Requirement: POLIS connects these related discussions into 1 coherent workstream,
        classifies it as completed by Hemant, and preserves the updates history.
        """
        now = datetime.now(timezone.utc)
        # Message 1: Lead discusses problem
        comm_repo.save(
            _build_comm(
                "msg_lead",
                "The email OTP verification flow is timing out in production.",
                "U_ALEX",
                "Alex",
                created_at=now - timedelta(hours=3),
                mentions=["U_HEMANT"],
            )
        )
        # Message 2: Colleague assigns task to Hemant
        comm_repo.save(
            _build_comm(
                "msg_assign",
                "Hemant, please fix the email OTP verification timeout bug.",
                "U_ALEX",
                "Alex",
                created_at=now - timedelta(hours=2),
                mentions=["U_HEMANT"],
            )
        )
        # Message 3: Hemant confirms completion
        comm_repo.save(
            _build_comm(
                "msg_confirm",
                "I have fixed the email OTP timeout bug and verified the verification flow in staging.",
                "U_HEMANT",
                "Hemant",
                created_at=now - timedelta(hours=1),
            )
        )

        summary = person_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            query_text="What has Hemant completed recently?",
        )

        # Should consolidate into 1 workstream
        assert len(summary.completed_work) == 1
        completed_item = summary.completed_work[0]
        assert "email OTP verification flow" in completed_item.work_item or "email" in completed_item.work_item.lower()
        # All updates preserved in workstream progression
        assert len(completed_item.updates) >= 2
        # Formatted response contains the completed flow
        assert "verification" in summary.formatted_response.lower()

    # -------------------------------------------------------------------------
    # 2. Questions / Inquiries Never Mistaken for Proof of Work
    # -------------------------------------------------------------------------

    def test_inquiries_about_someone_are_not_proof_of_work(self, comm_repo, person_service):
        """
        Colleague: 'Did Hemant finish the email OTP verification flow?'
        Colleague: 'Has Hemant deployed the hotfix?'

        Requirement: Do not confuse a question about someone's work with evidence that they performed that work.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm(
                "q1",
                "Did Hemant finish the email OTP verification flow?",
                "U_ALEX",
                "Alex",
                created_at=now - timedelta(hours=2),
                mentions=["U_HEMANT"],
            )
        )
        comm_repo.save(
            _build_comm(
                "q2",
                "Has Hemant deployed the hotfix?",
                "U_ALEX",
                "Alex",
                created_at=now - timedelta(hours=1),
                mentions=["U_HEMANT"],
            )
        )

        summary = person_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            query_text="What has Hemant completed this week?",
        )

        assert len(summary.completed_work) == 0
        assert len(summary.active_work) == 0
        assert "no recent work activity" in summary.formatted_response.lower()

    # -------------------------------------------------------------------------
    # 3. Conversational Continuity & Pronoun Resolution
    # -------------------------------------------------------------------------

    def test_multi_turn_continuity_resolves_he_and_pending_intent(self, engine, comm_repo):
        """
        Turn 1: User asks: 'What is Hemant working on?' -> returns Hemant's active/completed work.
        Turn 2: User asks: 'What has he completed?' -> 'he' resolves to Hemant; answers completed work.
        Turn 3: User asks: 'What is still pending?' -> resolves to Hemant; answers pending work.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm(
                "h1",
                "I am working on improving the knowledge base and shortlink accuracy.",
                "U_HEMANT",
                "Hemant",
                created_at=now - timedelta(hours=3),
            )
        )
        comm_repo.save(
            _build_comm(
                "h2",
                "The email verification and booking workflow fixes are complete.",
                "U_HEMANT",
                "Hemant",
                created_at=now - timedelta(hours=1),
            )
        )

        # Context for DM or Thread
        ctx = ConversationContext(user_id="U_AKSHAT", channel_id="D_TEST", thread_ts="", channel_type="im")

        # Turn 1
        q1 = Question(text="What is Hemant currently working on?", context=ctx, user_id="U_AKSHAT")
        ans1 = engine.ask(q1)
        assert ans1 is not None
        assert "knowledge base" in ans1.text.lower() or "shortlink" in ans1.text.lower()

        # Update context history as SlackIntentRouter does
        ctx = ctx.add_exchange(
            user_message="What is Hemant currently working on?",
            assistant_message=ans1.text,
            user_id="U_AKSHAT",
            user_metadata={"target_user_id": "U_HEMANT", "target_user_name": "Hemant"},
            assistant_metadata={"target_user_id": "U_HEMANT", "target_user_name": "Hemant"},
        )

        # Turn 2: Follow-up with pronoun 'he'
        q2 = Question(text="What has he completed?", context=ctx, user_id="U_AKSHAT")
        ans2 = engine.ask(q2)
        assert ans2 is not None
        assert "**Recently Completed**" in ans2.text
        assert "email verification" in ans2.text.lower() or "booking workflow" in ans2.text.lower()

        ctx = ctx.add_exchange(
            user_message="What has he completed?",
            assistant_message=ans2.text,
            user_id="U_AKSHAT",
            user_metadata={"target_user_id": "U_HEMANT", "target_user_name": "Hemant"},
            assistant_metadata={"target_user_id": "U_HEMANT", "target_user_name": "Hemant"},
        )

        # Turn 3: Follow-up on pending work
        q3 = Question(text="What is still pending?", context=ctx, user_id="U_AKSHAT")
        ans3 = engine.ask(q3)
        assert ans3 is not None
        assert "**Current Work**" in ans3.text
        assert "knowledge base" in ans3.text.lower() or "shortlink" in ans3.text.lower()

    # -------------------------------------------------------------------------
    # 4. Privacy Boundaries: DMs and Private Channels vs. Public Channels
    # -------------------------------------------------------------------------

    def test_private_messages_never_leak_to_public_channel_queries(self, person_service, comm_repo):
        """
        Hemant shares private updates in a DM / private channel:
        'I am working on the confidential executive reporting workflow.'
        And a public update in #engineering:
        'I am refining the shortlink accuracy.'

        Requirement:
        1. When a user asks in a public channel ('requester_channel_type=public'),
           the confidential private DM is completely excluded.
        2. When an authorized user asks in a DM, the private update is visible.
        3. When an unauthorized user asks in a DM, the private update is excluded.
        """
        now = datetime.now(timezone.utc)
        # Public channel message
        comm_repo.save(
            _build_comm(
                "pub_1",
                "I am refining the shortlink accuracy.",
                "U_HEMANT",
                "Hemant",
                channel_id="C_PUB",
                channel_name="engineering",
                channel_type="public",
                created_at=now - timedelta(hours=2),
            )
        )
        # Private DM between Hemant and Alex
        comm_repo.save(
            _build_comm(
                "priv_1",
                "I am working on the confidential executive reporting workflow.",
                "U_HEMANT",
                "Hemant",
                channel_id="D_HEMANT_ALEX",
                channel_name="directmessage",
                channel_type="im",
                created_at=now - timedelta(hours=1),
                mentions=["U_ALEX"],
            )
        )

        # 1. Asking in a public channel: MUST NOT contain confidential private DM
        summary_pub = person_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            requester_user_id="U_VIJAY",
            requester_channel_type="public",
        )
        assert "shortlink" in summary_pub.formatted_response.lower()
        assert "confidential" not in summary_pub.formatted_response.lower()

        # 2. Unauthorized user asking in DM: MUST NOT see private DM where they are not a participant
        summary_unauth = person_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            requester_user_id="U_VIJAY",
            requester_channel_type="im",
        )
        assert "confidential" not in summary_unauth.formatted_response.lower()

        # 3. Authorized participant (Alex) asking in DM: CAN see the DM
        summary_auth = person_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            requester_user_id="U_ALEX",
            requester_channel_type="im",
        )
        assert "confidential" in summary_auth.formatted_response.lower()

    # -------------------------------------------------------------------------
    # 5. Missing Information Communicated Honestly and Conversationally
    # -------------------------------------------------------------------------

    def test_unverified_completion_communicated_honestly(self, person_service, comm_repo):
        """
        Hemant is working on the email verification flow, but has not completed it.
        User asks: 'What has Hemant completed this week?'

        Requirement: POLIS honestly states that no confirmed completed tasks were found,
        does not mention active work as ongoing context or completed, and does not
        present unverified work as completed.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm(
                "w1",
                "I am working on the email OTP verification flow.",
                "U_HEMANT",
                "Hemant",
                created_at=now - timedelta(hours=2),
            )
        )

        summary = person_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            query_text="What has Hemant completed this week?",
        )

        assert len(summary.completed_work) == 0
        resp = summary.formatted_response
        assert "no confirmed completed tasks" in resp.lower()
        assert "ongoing" not in resp.lower()
        assert "email otp" not in resp.lower()
        assert "verification flow" not in resp.lower()
        assert "**Recently Completed**" not in resp
