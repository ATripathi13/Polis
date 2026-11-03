"""
Integration tests for complete person-specific recent work retrieval
and cognitive orchestration in POLIS.
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
from connectors.slack.models import (
    SlackChannel,
    SlackEvent,
    SlackMessage,
    SlackUser,
)
from connectors.slack.normalizers.slack_normalizer import SlackNormalizer
from domain.common.identifier import Identifier
from domain.operations import (
    InMemoryOperationalItemRepository,
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.reasoning import (
    Answer,
    Question,
    QuestionAnsweringService,
    SimpleReasoningService,
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
from domain.knowledge import (
    InMemoryKnowledgeRepository,
)


def _create_event(
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


class TestPersonWorkOrchestration:

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
    def engine(self, comm_repo, ops_repo, mock_identity) -> SimpleCognitiveEngine:
        kb_repo = InMemoryKnowledgeRepository()
        qa_service = MagicMock(spec=QuestionAnsweringService)
        qa_service.answer.return_value = Answer(
            text="Default generic handbook answer.",
            confidence=0.7,
        )

        pipeline = MagicMock(spec=PolisPipeline)
        planner = CognitivePlanner(identity_service=mock_identity)
        person_work_service = PersonWorkService(
            communication_repository=comm_repo,
            operational_item_repository=ops_repo,
            identity_service=mock_identity,
        )

        return SimpleCognitiveEngine(
            pipeline=pipeline,
            question_answering=qa_service,
            planner=planner,
            operational_item_repository=ops_repo,
            identity_resolver=mock_identity,
            person_work_service=person_work_service,
        )

    def test_scenario_a_current_user_end_to_end(self, engine, comm_repo):
        """
        Scenario A:
        Akshat: 'I am implementing the Organizational Event Engine.'
        Akshat: 'The Slack ingestion changes are complete.'
        Akshat: 'I will start the Calendar Agent after the event engine is finished.'
        Query: 'What am I currently working on?'
        Expected:
        - Resolves 'my' to authenticated requester Akshat
        - Intent: EMPLOYEE_WORK_QUERY
        - Returns structured active work, completed work, and commitment
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_create_event("msg_1", "I am implementing the Organizational Event Engine.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=3)))
        comm_repo.save(_create_event("msg_2", "The Slack ingestion changes are complete.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=2)))
        comm_repo.save(_create_event("msg_3", "I will start the Calendar Agent after the event engine is finished.", "U_AKSHAT", "Akshat", created_at=now - timedelta(hours=1)))

        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")
        question = Question(
            text="What am I currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )

        answer = engine.ask(question)

        assert answer is not None
        assert "**Current Work**" in answer.text
        assert "Organizational Event Engine" in answer.text
        assert "**Recently Completed**" in answer.text
        assert "Slack ingestion" in answer.text
        assert "**Assigned Work and Commitments**" in answer.text
        assert "Calendar Agent" in answer.text

    def test_scenario_b_another_employee_end_to_end(self, engine, comm_repo):
        """
        Scenario B:
        Gurkirat: 'I am refining the Canva graphics generation prompts.'
        Gurkirat: 'The workflow can now generate graphics from a topic or reference link.'
        Colleague: 'Gurkirat, please test the approval-to-post workflow.'
        Query: 'What is Gurkirat currently working on?'
        Expected:
        - Resolves target to Gurkirat (U_GURKIRAT)
        - Intent: EMPLOYEE_WORK_QUERY
        - Returns Canva graphics as active and approval-to-post as assigned
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_create_event("g_1", "I am refining the Canva graphics generation prompts.", "U_GURKIRAT", "Gurkirat", created_at=now - timedelta(hours=4)))
        comm_repo.save(_create_event("g_2", "The workflow can now generate graphics from a topic or reference link.", "U_GURKIRAT", "Gurkirat", created_at=now - timedelta(hours=3)))
        comm_repo.save(_create_event("g_3", "Gurkirat, please test the approval-to-post workflow.", "U_COLLEAGUE", "Colleague", mentions=["U_GURKIRAT"], created_at=now - timedelta(hours=1)))

        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")
        question = Question(
            text="What is Gurkirat currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )

        answer = engine.ask(question)

        assert answer is not None
        assert "Canva graphics" in answer.text or "refining" in answer.text
        assert "approval-to-post" in answer.text

    def test_scenario_c_thread_context_end_to_end(self, engine, comm_repo):
        """
        Scenario C:
        Parent: 'We need to improve the IVAN QA workflow.'
        Reply: 'I\'ve updated the testing personas. I still need to validate the remaining scenarios.'
        Query: 'What is Akshat working on?'
        Expected:
        - Thread parent context combined with reply progress
        """
        now = datetime.now(timezone.utc)
        parent = _create_event("parent_p1", "We need to improve the IVAN QA workflow.", "U_LEAD", "Lead", created_at=now - timedelta(hours=3))
        comm_repo.save(parent)

        reply = _create_event(
            "reply_r1",
            "I've updated the testing personas. I still need to validate the remaining scenarios.",
            "U_AKSHAT",
            "Akshat",
            correlation_id="parent_p1",
            created_at=now - timedelta(hours=1),
            metadata={
                "parent_message_body": "We need to improve the IVAN QA workflow.",
                "parent_actor_name": "Lead",
                "parent_actor_id": "U_LEAD",
            },
        )
        comm_repo.save(reply)

        question = Question(
            text="What is Akshat working on?",
            user_id="U_GURKIRAT",
        )

        answer = engine.ask(question)

        assert answer is not None
        assert "IVAN QA workflow" in answer.text or "testing personas" in answer.text

    def test_scenario_d_blocker_end_to_end(self, engine, comm_repo):
        """
        Scenario D:
        Message: 'The deployment is blocked because the API credentials are not available.'
        Query: 'What is this person blocked on?'
        Expected:
        - Blocker identified: API credentials
        - Traceable source channel and status
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(
            _create_event(
                "b_msg",
                "The deployment is blocked because the API credentials are not available.",
                "U_VIJAY",
                "Vijay",
                channel_name="infra-alerts",
                created_at=now - timedelta(hours=2),
            )
        )

        context = ConversationContext(
            user_id="U_VIJAY",
            channel_id="C_INFRA",
            thread_ts="",
            history=[{"user": "U_VIJAY", "author": "Vijay", "content": "The deployment is blocked because the API credentials are not available."}],
        )
        question = Question(
            text="What is this person blocked on?",
            context=context,
            target_user_id="U_VIJAY",
            target_user_name="Vijay",
        )

        answer = engine.ask(question)

        assert answer is not None
        assert "**Blockers and Dependencies**" in answer.text
        assert "API credentials" in answer.text

    def test_scenario_e_stale_information_override_end_to_end(self, engine, comm_repo):
        """
        Scenario E:
        Older message: 'I am working on the old API integration.'
        Newer message: 'The API integration is complete. I have started PDF preview improvements.'
        Query: 'What is Hemant currently working on?'
        Expected:
        - PDF preview improvements: Current Work
        - API integration: Recently Completed
        - Old API integration not listed under active work
        """
        now = datetime.now(timezone.utc)
        comm_repo.save(_create_event("old_h", "I am working on the old API integration.", "U_HEMANT", "Hemant", created_at=now - timedelta(days=2)))
        comm_repo.save(_create_event("new_h", "The API integration is complete. I have started PDF preview improvements.", "U_HEMANT", "Hemant", created_at=now - timedelta(hours=1)))

        question = Question(
            text="What is Hemant currently working on?",
            user_id="U_AKSHAT",
        )

        answer = engine.ask(question)

        assert answer is not None
        assert "PDF preview" in answer.text
        assert "**Recently Completed**" in answer.text
        assert "API integration" in answer.text

    def test_ambiguous_employee_identity_requires_clarification(self, engine):
        """
        Requirement 8 & Test 12:
        When multiple team members match an explicit name ('Alex'),
        POLIS must return an explicit clarification request listing the candidates.
        """
        question = Question(
            text="What is Alex working on?",
            user_id="U_AKSHAT",
        )

        answer = engine.ask(question)

        assert answer is not None
        assert "Multiple team members match that name" in answer.text
        assert "Alex Smith" in answer.text
        assert "Alex Wong" in answer.text

    def test_empty_results_does_not_fallback_to_generic_kb(self, engine):
        """
        Requirement & Test 13:
        When no recent work is found for an employee, explain the searched
        lookback window instead of falling back to unrelated generic KB articles.
        """
        question = Question(
            text="What has Hemant completed this week?",
            user_id="U_AKSHAT",
        )

        answer = engine.ask(question)

        assert answer is not None
        # Must NOT be the default generic QA mock answer
        assert answer.text != "Default generic handbook answer."
        assert "7 days" in answer.text
        assert "no recent work activity" in answer.text.lower()

    def test_formal_task_query_regression(self, engine):
        """
        Test 14:
        Formal task queries like 'What are open tasks in the tracker?'
        must preserve existing TASK_QUERY behavior and not be hijacked.
        """
        planner = engine.planner
        plan = planner.plan("Show all open tasks in the operations tracker")
        assert plan.intent == IntentCategory.TASK_QUERY

    def test_slack_normalizer_mention_extraction(self, mock_identity):
        """
        Defect 6 & Test 6:
        SlackNormalizer.normalize() extracts <@U12345> and multiple mentions.
        """
        normalizer = SlackNormalizer(identity_service=mock_identity)
        slack_event = SlackEvent(
            user=SlackUser(user_id="U_SENDER", username="sender"),
            channel=SlackChannel(channel_id="C_DEV", name="engineering"),
            message=SlackMessage(
                text="Hey <@U_AKSHAT> and <@U_GURKIRAT|gurkirat>, please review the PR.",
                ts="1710000000.000100",
            ),
        )

        comm = normalizer.normalize(slack_event)

        assert comm is not None
        mention_ids = [m.identity.internal_id for m in comm.mentions]
        assert "U_AKSHAT" in mention_ids
        assert "U_GURKIRAT" in mention_ids
