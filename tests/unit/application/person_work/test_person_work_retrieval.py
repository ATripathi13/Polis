"""
Unit tests for person-specific recent work retrieval, classification,
and synthesis in POLIS.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from application.identity import CanonicalIdentityService, IdentityResolutionStatus
from application.person_work.person_work_service import (
    ExtractedWorkItem,
    PersonWorkService,
    PersonWorkSummary,
    WorkActivityType,
)
from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.operations.repositories.in_memory_operational_item_repository import (
    InMemoryOperationalItemRepository,
)
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
    Mention,
)
from engines.communication.infrastructure.repositories.memory_repository import (
    InMemoryCommunicationRepository,
)


def _build_comm_event(
    event_id: str,
    text: str,
    actor_id: str,
    actor_name: str,
    channel_id: str = "C_DEV",
    channel_name: str = "general-dev",
    channel_type: str = "public",
    created_at: datetime | None = None,
    correlation_id: str | None = None,
    mentions: list[Any] | None = None,
    metadata: dict | None = None,
) -> CommunicationEvent:
    now = created_at or datetime.now(timezone.utc)
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
    ev.created_at = now
    return ev


class TestPersonWorkRetrieval:

    @pytest.fixture
    def comm_repo(self) -> InMemoryCommunicationRepository:
        return InMemoryCommunicationRepository()

    @pytest.fixture
    def ops_repo(self) -> InMemoryOperationalItemRepository:
        return InMemoryOperationalItemRepository()

    @pytest.fixture
    def mock_identity_service(self) -> MagicMock:
        service = MagicMock()
        users = [
            {"id": "U_AKSHAT", "name": "akshat", "real_name": "Akshat Tripathi", "profile": {"display_name": "Akshat"}},
            {"id": "U_GURKIRAT", "name": "gurkirat", "real_name": "Gurkirat Singh", "profile": {"display_name": "Gurkirat"}},
            {"id": "U_HEMANT", "name": "hemant", "real_name": "Hemant Sharma", "profile": {"display_name": "Hemant"}},
            {"id": "U_VIJAY", "name": "vijay", "real_name": "Vijay Kumar", "profile": {"display_name": "Vijay"}},
            {"id": "U_ALEX1", "name": "alex.s", "real_name": "Alex Smith", "profile": {"display_name": "Alex Smith"}},
            {"id": "U_ALEX2", "name": "alex.w", "real_name": "Alex Wong", "profile": {"display_name": "Alex Wong"}},
        ]
        service.get_workspace_users.return_value = users

        def _get_display_name(uid):
            for u in users:
                if u["id"] == uid:
                    return u["profile"]["display_name"]
            return uid
        service.get_display_name.side_effect = _get_display_name
        service.get_all_identifiers_for_user.side_effect = lambda uid: [uid]
        return service

    @pytest.fixture
    def work_service(self, comm_repo, ops_repo, mock_identity_service) -> PersonWorkService:
        return PersonWorkService(
            communication_repository=comm_repo,
            operational_item_repository=ops_repo,
            identity_service=mock_identity_service,
        )

    def test_actor_sql_filtering_before_limits_and_no_literal_overlap(self, comm_repo, work_service):
        """
        Defects 3 & 4:
        Actor filtering must happen in repository before limits,
        and messages must not be dropped just because they lack literal query words
        like 'summary', 'work', or 'priorities'.
        """
        now = datetime.now(timezone.utc)
        # Seed 120 messages from OTHER users to exceed limit=100
        for i in range(120):
            comm_repo.save(
                _build_comm_event(
                    event_id=f"other_{i}",
                    text=f"Irrelevant chat message {i}",
                    actor_id="U_OTHER",
                    actor_name="Other User",
                    created_at=now - timedelta(hours=2, minutes=i),
                )
            )

        # Seed target user message with NO literal keywords like "work", "summary", "priorities"
        comm_repo.save(
            _build_comm_event(
                event_id="akshat_msg_1",
                text="I am implementing the Organizational Event Engine.",
                actor_id="U_AKSHAT",
                actor_name="Akshat",
                created_at=now - timedelta(hours=1),
            )
        )

        results = comm_repo.get_person_recent_activity(
            actor_ids=["U_AKSHAT"],
            actor_name="Akshat",
            start_time=now - timedelta(days=7),
            end_time=now + timedelta(hours=1),
            limit=20,
        )

        assert len(results) == 1
        assert results[0].source_event_id == "akshat_msg_1"
        assert "Organizational Event Engine" in results[0].content.body

        # Also verify search method preserves actor filtering without literal query match requirement
        search_results = comm_repo.search(
            query="summary of my current work and priorities",
            actor_id="U_AKSHAT",
            limit=20,
        )
        assert len(search_results) == 1
        assert search_results[0].source_event_id == "akshat_msg_1"

    def test_scenario_a_current_user_recent_work(self, comm_repo, work_service):
        """
        Scenario A:
        Akshat: 'I am implementing the Organizational Event Engine.' -> Active work
        Akshat: 'The Slack ingestion changes are complete.' -> Completed work
        Akshat: 'I will start the Calendar Agent after the event engine is finished.' -> Commitment
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_comm_event("msg_1", "I am implementing the Organizational Event Engine.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=3)))
        comm_repo.save(_build_comm_event("msg_2", "The Slack ingestion changes are complete.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=2)))
        comm_repo.save(_build_comm_event("msg_3", "I will start the Calendar Agent after the event engine is finished.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=1)))

        summary = work_service.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
            requester_user_id="U_AKSHAT",
        )

        assert len(summary.active_work) >= 1
        assert any("Organizational Event Engine" in item.work_item for item in summary.active_work)

        assert len(summary.completed_work) >= 1
        assert any("Slack ingestion" in item.work_item for item in summary.completed_work)

        assert len(summary.commitments) >= 1
        assert any("Calendar Agent" in item.work_item for item in summary.commitments)

        formatted = summary.formatted_response
        assert "**Current Work**" in formatted
        assert "**Assigned Work and Commitments**" in formatted
        assert "**Recently Completed**" in formatted

    def test_scenario_b_another_employee_and_assignment(self, comm_repo, work_service):
        """
        Scenario B:
        Gurkirat: 'I am refining the Canva graphics generation prompts.' -> Active work
        Gurkirat: 'The workflow can now generate graphics from a topic or reference link.' -> Progress update (Active)
        Another: 'Gurkirat, please test the approval-to-post workflow.' -> Assigned work
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_build_comm_event("g_1", "I am refining the Canva graphics generation prompts.", "U_GURKIRAT", "Gurkirat", created_at=now - timedelta(hours=4)))
        comm_repo.save(_build_comm_event("g_2", "The workflow can now generate graphics from a topic or reference link.", "U_GURKIRAT", "Gurkirat", created_at=now - timedelta(hours=3)))
        comm_repo.save(_build_comm_event("g_3", "Gurkirat, please test the approval-to-post workflow.", "U_COLLEAGUE", "Colleague", mentions=["U_GURKIRAT"], created_at=now - timedelta(hours=1)))

        summary = work_service.get_person_work_summary(
            target_user_id="U_GURKIRAT",
            target_user_name="Gurkirat",
            requester_user_id="U_AKSHAT",
        )

        assert any("Canva graphics" in item.work_item or "refining" in item.work_item for item in summary.active_work)
        assert any("approval-to-post" in item.work_item for item in summary.assigned_work)
        formatted = summary.formatted_response
        assert "Gurkirat" in formatted or "approval-to-post" in formatted

    def test_scenario_c_thread_context_and_parent_attribution(self, comm_repo, work_service):
        """
        Scenario C:
        Parent: 'We need to improve the IVAN QA workflow.'
        Reply from Akshat: 'I\'ve updated the testing personas. I still need to validate the remaining scenarios.'
        Expected:
        - Parent context attached to reply
        - Updated testing personas classified as progress
        - Remaining scenario validation classified as pending work
        - Parent author not mistakenly attributed to Akshat
        """
        now = datetime.now(timezone.utc)
        # Parent message
        parent = _build_comm_event("parent_100", "We need to improve the IVAN QA workflow.", "U_MANAGER", "Manager", created_at=now - timedelta(hours=2))
        comm_repo.save(parent)

        # Thread reply
        reply = _build_comm_event(
            "reply_101",
            "I've updated the testing personas. I still need to validate the remaining scenarios.",
            "U_AKSHAT",
            "Akshat",
            correlation_id="parent_100",
            created_at=now - timedelta(hours=1),
            metadata={
                "parent_message_body": "We need to improve the IVAN QA workflow.",
                "parent_actor_name": "Manager",
                "parent_actor_id": "U_MANAGER",
            },
        )
        comm_repo.save(reply)

        summary = work_service.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
        )

        # Verify parent context is referenced and Akshat is the item person
        items = summary.items
        assert any("IVAN QA workflow" in item.work_item or "testing personas" in item.work_item for item in items)
        for item in items:
            assert item.person_id == "U_AKSHAT"

    def test_scenario_d_blocker_identification(self, comm_repo, work_service):
        """
        Scenario D:
        Message: 'The deployment is blocked because the API credentials are not available.'
        Query: 'What is this person blocked on?'
        Expected:
        - Blocker identified: API credentials
        - Person attributed correctly
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm_event(
                "block_1",
                "The deployment is blocked because the API credentials are not available.",
                "U_VIJAY",
                "Vijay",
                channel_name="deployments",
                created_at=now - timedelta(hours=2),
            )
        )

        summary = work_service.get_person_work_summary(
            target_user_id="U_VIJAY",
            target_user_name="Vijay",
        )

        assert len(summary.blockers) >= 1
        assert any("API credentials" in item.work_item or "credentials" in item.latest_update for item in summary.blockers)
        formatted = summary.formatted_response
        assert "**Blockers and Dependencies**" in formatted
        assert "API credentials" in formatted

    def test_scenario_e_recency_precedence_over_stale_status(self, comm_repo, work_service):
        """
        Scenario E:
        Older message: 'I am working on the old API integration.'
        Newer message: 'The API integration is complete. I have started PDF preview improvements.'
        Expected:
        - API integration classified as COMPLETED
        - PDF preview improvements classified as ACTIVE
        - Old API integration does not remain active
        """
        now = datetime.now(timezone.utc)
        # Older message: active on API integration
        comm_repo.save(
            _build_comm_event(
                "old_msg",
                "I am working on the old API integration.",
                "U_HEMANT",
                "Hemant",
                created_at=now - timedelta(days=3),
            )
        )
        # Newer message: complete on API integration, started PDF preview
        comm_repo.save(
            _build_comm_event(
                "new_msg",
                "The API integration is complete. I have started PDF preview improvements.",
                "U_HEMANT",
                "Hemant",
                created_at=now - timedelta(hours=2),
            )
        )

        summary = work_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
        )

        # PDF preview should be active work
        assert any("PDF preview" in item.work_item for item in summary.active_work)
        # API integration should be in completed_work, NOT in active_work
        assert any("API integration" in item.work_item for item in summary.completed_work)
        assert not any("old API integration" in item.work_item and item.activity_type == WorkActivityType.ACTIVE_WORK for item in summary.active_work)

    def test_multiple_identifiers_preserve_canonical_person_id(self, comm_repo, work_service):
        """
        Regression:
        Messages found through an additional employee identifier must retain
        the canonical employee ID in every extracted work item.
        """
        work_service._identity_service.get_all_identifiers_for_user.side_effect = (
            lambda uid: [uid, "SLACK_HEMANT"] if uid == "U_HEMANT" else [uid]
        )

        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm_event(
                "hemant_alias_msg",
                "I am implementing the Organizational Event Engine.",
                "SLACK_HEMANT",
                "Hemant",
                created_at=now - timedelta(hours=1),
            )
        )

        summary = work_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
        )

        assert summary.items
        assert any(
            "Organizational Event Engine" in item.work_item
            for item in summary.active_work
        )
        assert all(item.person_id == "U_HEMANT" for item in summary.items)


    def test_empty_results_data_limitations_explanation(self, comm_repo, work_service):
        """
        Defect 13:
        When no recent work is found, explain the searched lookback period
        instead of returning blank or falling back to generic KB data.
        """
        summary = work_service.get_person_work_summary(
            target_user_id="U_EMPTY",
            target_user_name="New Person",
            lookback_days=7,
        )

        assert len(summary.items) == 0
        formatted = summary.formatted_response
        assert "7 days" in formatted
        assert "no recent work activity" in formatted.lower()

    def test_private_channel_boundary_isolation(self, comm_repo, work_service):
        """
        Requirement:
        Private channel/DM messages of employee A must not be leaked
        when employee B queries work.
        """
        now = datetime.now(timezone.utc)
        # Private DM message
        comm_repo.save(
            _build_comm_event(
                "dm_1",
                "I am working on private salary review.",
                "U_MANAGER",
                "Manager",
                channel_id="D_PRIVATE",
                channel_type="im",
                created_at=now - timedelta(hours=1),
            )
        )

        # Unauthorized requester queries manager
        summary = work_service.get_person_work_summary(
            target_user_id="U_MANAGER",
            target_user_name="Manager",
            requester_user_id="U_OTHER_EMPLOYEE",
        )

        # Private item must be omitted
        assert not any("salary review" in item.work_item for item in summary.items)

    def test_mention_objects_with_nested_dicts_do_not_raise_type_error(self, comm_repo, work_service):
        """
        Regression:
        Mention objects with nested dictionaries (external_ids, metadata)
        must not raise TypeError: unhashable type: 'dict' in private channels.
        """
        now = datetime.now(timezone.utc)
        mention_with_dicts = Mention(
            identity=CommunicationIdentity(
                internal_id="U_COLLEAGUE",
                external_ids={"slack": "U_COLLEAGUE", "email": "colleague@example.com"},
                metadata={"role": "engineer", "department": "core"},
            ),
            display_name="Colleague Display Name",
        )
        comm_repo.save(
            _build_comm_event(
                "priv_msg_1",
                "I am working on the database encryption module.",
                "U_AKSHAT",
                "Akshat",
                channel_id="C_PRIVATE_SEC",
                channel_type="private",
                created_at=now - timedelta(hours=1),
                mentions=[mention_with_dicts],
            )
        )

        # Query by the mentioned user - must succeed without TypeError
        summary = work_service.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
            requester_user_id="U_COLLEAGUE",
            requester_channel_type="private",
        )
        assert any("database encryption module" in item.work_item for item in summary.active_work)

    def test_valid_mention_identity_added_to_authorization_set(self, comm_repo, work_service):
        """
        Mentioned user's internal_id allows them to access work communicated in private channels.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm_event(
                "priv_msg_auth",
                "I am working on the caching layers.",
                "U_HEMANT",
                "Hemant",
                channel_id="C_PRIVATE_PERF",
                channel_type="private",
                created_at=now - timedelta(hours=1),
                mentions=[
                    Mention(
                        identity=CommunicationIdentity(
                            internal_id="U_VIJAY",
                            external_ids={"slack": "U_VIJAY"},
                        ),
                        display_name="Vijay",
                    )
                ],
            )
        )

        # U_VIJAY was mentioned, so U_VIJAY is authorized
        summary_auth = work_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            requester_user_id="U_VIJAY",
            requester_channel_type="private",
        )
        assert any("caching layers" in item.work_item for item in summary_auth.active_work)

    def test_missing_or_malformed_mention_identities_safely_ignored(self, comm_repo, work_service):
        """
        Missing, empty, or malformed mention identities must not crash
        and must never authorize unauthorized users. Display names must not be used as auth IDs.
        """
        now = datetime.now(timezone.utc)
        mock_bad_mention_1 = MagicMock()
        mock_bad_mention_1.identity = None
        mock_bad_mention_1.display_name = "U_UNAUTHORIZED"

        mock_bad_mention_2 = MagicMock(spec=[])  # no identity attribute at all

        mock_bad_mention_3 = MagicMock()
        mock_bad_mention_3.identity = MagicMock()
        mock_bad_mention_3.identity.internal_id = "   "  # whitespace-only ID

        mock_bad_mention_4 = MagicMock()
        mock_bad_mention_4.identity = MagicMock()
        mock_bad_mention_4.identity.internal_id = None  # None ID

        comm_repo.save(
            _build_comm_event(
                "priv_msg_malformed",
                "I am working on the auth middleware.",
                "U_HEMANT",
                "Hemant",
                channel_id="C_PRIVATE_AUTH",
                channel_type="private",
                created_at=now - timedelta(hours=1),
                mentions=[
                    mock_bad_mention_1,
                    mock_bad_mention_2,
                    mock_bad_mention_3,
                    mock_bad_mention_4,
                    None,  # None element
                    12345,  # non-object element
                ],
            )
        )

        # Query by unauthorized user whose ID happens to match display_name of bad mention 1
        summary = work_service.get_person_work_summary(
            target_user_id="U_HEMANT",
            target_user_name="Hemant",
            requester_user_id="U_UNAUTHORIZED",
            requester_channel_type="private",
        )
        assert not any("auth middleware" in item.work_item for item in summary.items)

    def test_unauthorized_requester_excluded_from_private_channel_evidence(self, comm_repo, work_service):
        """
        An unauthorized requester not in actor, channel id, members, or mentions
        cannot access private channel evidence.
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _build_comm_event(
                "priv_msg_secret",
                "I am auditing security vulnerabilities in backend API.",
                "U_AKSHAT",
                "Akshat",
                channel_id="C_PRIVATE_AUDIT",
                channel_type="private",
                created_at=now - timedelta(hours=1),
                mentions=[
                    Mention(
                        identity=CommunicationIdentity(
                            internal_id="U_HEMANT",
                            external_ids={"slack": "U_HEMANT"},
                        ),
                        display_name="Hemant",
                    )
                ],
            )
        )

        # U_STRANGER is not mentioned, not actor, not in channel
        summary = work_service.get_person_work_summary(
            target_user_id="U_AKSHAT",
            target_user_name="Akshat",
            requester_user_id="U_STRANGER",
            requester_channel_type="private",
        )
        assert not any("security vulnerabilities" in item.work_item for item in summary.items)

    def test_public_channel_and_dm_permissions_remain_unchanged(self, comm_repo, work_service):
        """
        Existing public-channel access and DM boundary protections remain intact:
        1. Public channel work is accessible to any requester.
        2. Inaccessible private/DM work is never used to answer a public-channel query.
        3. DM participant (actor or member) can view work when querying in private/DM context.
        """
        now = datetime.now(timezone.utc)
        # Public message
        comm_repo.save(
            _build_comm_event(
                "pub_msg_1",
                "I am developing the public landing page.",
                "U_GURKIRAT",
                "Gurkirat",
                channel_id="C_GENERAL",
                channel_type="public",
                created_at=now - timedelta(hours=1),
            )
        )
        # DM message between Gurkirat and Hemant
        comm_repo.save(
            _build_comm_event(
                "dm_msg_1",
                "I am working on the private compensation adjustment.",
                "U_GURKIRAT",
                "Gurkirat",
                channel_id="D_U_GURKIRAT_U_HEMANT",
                channel_type="im",
                created_at=now - timedelta(hours=1),
            )
        )

        # 1. Any requester in public channel sees public work
        summary_pub = work_service.get_person_work_summary(
            target_user_id="U_GURKIRAT",
            target_user_name="Gurkirat",
            requester_user_id="U_RANDOM",
            requester_channel_type="public",
        )
        assert any("public landing page" in item.work_item for item in summary_pub.active_work)
        # But NOT private DM work
        assert not any("compensation adjustment" in item.work_item for item in summary_pub.items)

        # 2. DM participant (Hemant, channel_id contains U_HEMANT) sees DM work
        summary_dm = work_service.get_person_work_summary(
            target_user_id="U_GURKIRAT",
            target_user_name="Gurkirat",
            requester_user_id="U_HEMANT",
            requester_channel_type="im",
        )
        assert any("compensation adjustment" in item.work_item for item in summary_dm.active_work)
