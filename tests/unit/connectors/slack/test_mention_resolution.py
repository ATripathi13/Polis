"""
Focused regression tests for @Person and Slack mention resolution in Employee Work Intelligence.

Covers all required scenarios:
- Question uses employee name
- Question uses <@USER_ID>
- Question uses <@USER_ID|username>
- Plain-text @Name mentions
- Tagged employee in a channel
- Tagged employee in a DM
- Unknown Slack user ID (no incorrect attribution)
- Ambiguous display name (clarification prompted, no silent guess)
- Two employees with similar names (disambiguated by Slack user ID)
- Question about requester (self-work preserved)
- Employee work evidence isolation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from application.activity import ActivityDetector
from application.cognitive import CognitivePlanner, SimpleCognitiveEngine
from domain.reasoning import ConversationContext, Question, QuestionAnsweringService
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from infrastructure.database.conversation_repository import InMemoryConversationRepository
from application.person_work.person_work_service import PersonWorkService
from domain.common.identifier import Identifier
from engines.communication.infrastructure.repositories.memory_repository import (
    InMemoryCommunicationRepository,
)
from domain.operations import InMemoryOperationalItemRepository
from domain.knowledge import InMemoryKnowledgeRepository
from application.pipeline.pipeline import PolisPipeline
from engines.slack.dto import SlackMessage
from engines.slack.router import SlackIntentRouter


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


class TestSlackMentionResolution:

    @pytest.fixture
    def comm_repo(self) -> InMemoryCommunicationRepository:
        repo = InMemoryCommunicationRepository()
        now = datetime.now(timezone.utc)

        # Seed realistic work communications
        repo.save(_create_event(
            "msg_gurkirat_1",
            "I am implementing the new Canva graphics generation workflow.",
            "U_GURKIRAT",
            "Gurkirat",
            created_at=now - timedelta(hours=5),
        ))
        repo.save(_create_event(
            "msg_gurkirat_2",
            "I've completed the webinar slides and podcast assets.",
            "U_GURKIRAT",
            "Gurkirat",
            created_at=now - timedelta(hours=3),
        ))

        repo.save(_create_event(
            "msg_hemant_1",
            "I am working on the chatbot latency and response streaming.",
            "U_HEMANT",
            "Hemant",
            created_at=now - timedelta(hours=4),
        ))
        repo.save(_create_event(
            "msg_hemant_2",
            "Finished migrating the embedding pipeline to the new vector index.",
            "U_HEMANT",
            "Hemant",
            created_at=now - timedelta(hours=2),
        ))

        repo.save(_create_event(
            "msg_vijay_1",
            "I am setting up the Circle community integration.",
            "U_VIJAY",
            "Vijay",
            created_at=now - timedelta(hours=6),
        ))

        repo.save(_create_event(
            "msg_alex1_1",
            "I am reviewing the security compliance checklist.",
            "U_ALEX1",
            "Alex Smith",
            created_at=now - timedelta(hours=4),
        ))
        repo.save(_create_event(
            "msg_alex2_1",
            "I am tuning the postgres connection pool settings.",
            "U_ALEX2",
            "Alex Wong",
            created_at=now - timedelta(hours=4),
        ))

        repo.save(_create_event(
            "msg_akshat_1",
            "I am implementing person-specific work retrieval.",
            "U_AKSHAT",
            "Akshat",
            created_at=now - timedelta(hours=1),
        ))

        return repo

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
            {"id": "U_BOT", "name": "polis", "real_name": "POLIS Bot", "profile": {"display_name": "POLIS"}},
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
        qa_service.answer.return_value = None

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

    @pytest.fixture
    def conv_repo(self) -> InMemoryConversationRepository:
        return InMemoryConversationRepository()

    @pytest.fixture
    def mock_responder(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def router(self, engine, mock_responder, conv_repo, mock_identity) -> SlackIntentRouter:
        return SlackIntentRouter(
            engine=engine,
            responder=mock_responder,
            connector=MagicMock(),
            conversation_repository=conv_repo,
            identity_service=mock_identity,
            activity_detector=ActivityDetector(),
        )

    # --------------------------------------------------------------------------
    # 1. Question uses employee name (Existing behaviour preserved)
    # --------------------------------------------------------------------------
    def test_question_uses_employee_name_resolves_and_returns_work(self, engine):
        """Scenario: User asks by plain name 'What is Hemant currently working on?'"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")
        question = Question(
            text="What is Hemant currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        answer = engine.ask(question)
        assert answer is not None
        assert "chatbot latency" in answer.text.lower() or "chatbot" in answer.text.lower()
        # Ensure it didn't return Gurkirat or Vijay's work
        assert "canva" not in answer.text.lower()
        assert "circle" not in answer.text.lower()

    # --------------------------------------------------------------------------
    # 2. Question uses <@USER_ID> (Correct employee resolved)
    # --------------------------------------------------------------------------
    def test_question_uses_raw_slack_mention_resolves_correct_employee(self, engine):
        """Scenario: User asks using '<@U_GURKIRAT>' or '<@U_HEMANT>, summarize his recent work.'"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")

        # Test 1: "What is <@U_GURKIRAT> currently working on?"
        q1 = Question(
            text="What is <@U_GURKIRAT> currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        ans1 = engine.ask(q1)
        assert ans1 is not None
        assert "canva" in ans1.text.lower()
        assert "chatbot" not in ans1.text.lower()

        # Test 2: "<@U_HEMANT>, summarize his recent work."
        q2 = Question(
            text="<@U_HEMANT>, summarize his recent work.",
            context=context,
            user_id="U_AKSHAT",
        )
        ans2 = engine.ask(q2)
        assert ans2 is not None
        assert "chatbot" in ans2.text.lower()
        assert "canva" not in ans2.text.lower()

    # --------------------------------------------------------------------------
    # 3. Question uses <@USER_ID|username> (Correct employee resolved)
    # --------------------------------------------------------------------------
    def test_question_uses_slack_mention_with_pipe_label(self, engine):
        """Scenario: User mentions using '<@U_GURKIRAT|gurkirat>' or '<@U_HEMANT|hemant>'"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")

        q1 = Question(
            text="What is <@U_GURKIRAT|gurkirat> currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        ans1 = engine.ask(q1)
        assert ans1 is not None
        assert "canva" in ans1.text.lower()

        q2 = Question(
            text="<@U_HEMANT|hemant>, summarize his recent work.",
            context=context,
            user_id="U_AKSHAT",
        )
        ans2 = engine.ask(q2)
        assert ans2 is not None
        assert "chatbot" in ans2.text.lower()

    # --------------------------------------------------------------------------
    # 4. Plain-text @Name mentions (e.g. "@Gurkirat", "@Hemant")
    # --------------------------------------------------------------------------
    def test_plain_text_at_mention_resolves_correct_employee(self, engine):
        """Scenario: User types 'What is @Gurkirat currently working on?' and '@Hemant, summarize his recent work.'"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")

        q1 = Question(
            text="What is @Gurkirat currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        ans1 = engine.ask(q1)
        assert ans1 is not None
        assert "canva" in ans1.text.lower()

        q2 = Question(
            text="@Hemant, summarize his recent work.",
            context=context,
            user_id="U_AKSHAT",
        )
        ans2 = engine.ask(q2)
        assert ans2 is not None
        assert "chatbot" in ans2.text.lower()

    # --------------------------------------------------------------------------
    # 5. Tagged employee in a channel
    # --------------------------------------------------------------------------
    def test_tagged_employee_in_channel_end_to_end(self, router, mock_responder):
        """Scenario: Tagged employee in a public/private channel via SlackIntentRouter"""
        msg = SlackMessage(
            user="U_AKSHAT",
            channel="C_DEV",
            text="<@U_BOT> What is <@U_GURKIRAT> currently working on?",
            ts="101.1",
            event_ts="101.1",
            thread_ts=None,
        )
        mock_responder.reset_mock()
        router.handle(msg)

        assert mock_responder.reply.called
        reply_call = mock_responder.reply.call_args[1]
        assert reply_call["channel"] == "C_DEV"
        assert reply_call["thread_ts"] == "101.1"
        assert "canva" in reply_call["text"].lower()
        assert "chatbot" not in reply_call["text"].lower()

    # --------------------------------------------------------------------------
    # 6. Tagged employee in a DM
    # --------------------------------------------------------------------------
    def test_tagged_employee_in_dm_end_to_end(self, router, mock_responder):
        """Scenario: Tagged employee in a 1:1 Slack DM via SlackIntentRouter"""
        msg = SlackMessage(
            user="U_AKSHAT",
            channel="D_AKSHAT",
            text="What is @Gurkirat currently working on?",
            ts="202.1",
            event_ts="202.1",
            thread_ts=None,
        )
        mock_responder.reset_mock()
        router.handle(msg)

        assert mock_responder.reply.called
        reply_call = mock_responder.reply.call_args[1]
        assert reply_call["channel"] == "D_AKSHAT"
        assert "canva" in reply_call["text"].lower()

    # --------------------------------------------------------------------------
    # 7. Unknown Slack user ID (No incorrect attribution)
    # --------------------------------------------------------------------------
    def test_unknown_slack_user_id_does_not_attribute_incorrectly(self, engine):
        """Scenario: User asks about '<@U_UNKNOWN_999>', must not substitute another employee"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")
        question = Question(
            text="What is <@U_UNKNOWN_999> currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        answer = engine.ask(question)
        assert answer is not None
        # Must not report Canva, Chatbot, or Circle work
        assert "canva" not in answer.text.lower()
        assert "chatbot" not in answer.text.lower()
        assert "circle" not in answer.text.lower()
        # Must state that no work was found for the user
        assert "u_unknown_999" in answer.text.lower() or "couldn't find" in answer.text.lower() or "no recent work" in answer.text.lower()

    def test_unknown_slack_user_id_with_pipe_label_does_not_resolve_to_different_employee(self, router, mock_responder):
        """Scenario: Mention '<@U_UNKNOWN|Gurkirat>' must not resolve to workspace employee Gurkirat (U_GURKIRAT)"""
        # 1. Direct router._resolve_target_user check
        resolved = router._resolve_target_user(
            text="What is <@U_UNKNOWN|Gurkirat> working on?",
            requester_user_id="U_AKSHAT",
        )
        assert resolved is not None
        assert resolved["id"] == "U_UNKNOWN"
        assert resolved["id"] != "U_GURKIRAT"
        assert resolved["name"] != "Gurkirat"

        # 2. End-to-end check: must not attribute Gurkirat's work (Canva) to U_UNKNOWN
        msg = SlackMessage(
            user="U_AKSHAT",
            channel="C_DEV",
            text="<@U_BOT> What is <@U_UNKNOWN|Gurkirat> currently working on?",
            ts="707.1",
            event_ts="707.1",
            thread_ts=None,
        )
        mock_responder.reset_mock()
        router.handle(msg)

        assert mock_responder.reply.called
        reply_call = mock_responder.reply.call_args[1]
        reply_text = reply_call["text"].lower()
        assert "canva" not in reply_text
        assert "no recent work" in reply_text or "found no recent" in reply_text

    # --------------------------------------------------------------------------
    # 8. Ambiguous display name (Clarification prompted, no silent guess)
    # --------------------------------------------------------------------------
    def test_ambiguous_display_name_requires_clarification(self, router, mock_responder):
        """Scenario: Workspace has two Alexes (Alex Smith, Alex Wong); 'What is Alex working on?' prompts clarification"""
        msg = SlackMessage(
            user="U_AKSHAT",
            channel="C_DEV",
            text="<@U_BOT> What is Alex working on?",
            ts="303.1",
            event_ts="303.1",
            thread_ts=None,
        )
        mock_responder.reset_mock()
        router.handle(msg)

        assert mock_responder.reply.called
        reply_call = mock_responder.reply.call_args[1]
        reply_text = reply_call["text"]
        assert "Multiple team members match that name" in reply_text
        assert "Alex Smith" in reply_text
        assert "Alex Wong" in reply_text

    # --------------------------------------------------------------------------
    # 9. Two employees with similar names (Disambiguated by Slack user ID)
    # --------------------------------------------------------------------------
    def test_two_employees_with_similar_names_disambiguated_by_slack_user_id(self, engine):
        """Scenario: Using Slack user ID disambiguates between Alex Smith and Alex Wong"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")

        # Query specifically for Alex Smith using <@U_ALEX1>
        q1 = Question(
            text="What is <@U_ALEX1> currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        ans1 = engine.ask(q1)
        assert ans1 is not None
        assert "security compliance" in ans1.text.lower()
        assert "postgres" not in ans1.text.lower()

        # Query specifically for Alex Wong using <@U_ALEX2|alex.w>
        q2 = Question(
            text="<@U_ALEX2|alex.w>, summarize his recent work.",
            context=context,
            user_id="U_AKSHAT",
        )
        ans2 = engine.ask(q2)
        assert ans2 is not None
        assert "postgres" in ans2.text.lower()
        assert "security compliance" not in ans2.text.lower()

    # --------------------------------------------------------------------------
    # 10. Question about requester (Self-work preserved)
    # --------------------------------------------------------------------------
    def test_question_about_requester_preserves_self_work(self, engine):
        """Scenario: User asks about own work 'What am I currently working on?'"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")
        question = Question(
            text="What am I currently working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        answer = engine.ask(question)
        assert answer is not None
        assert "person-specific work retrieval" in answer.text.lower()
        # Must not confuse with other employees' work
        assert "canva" not in answer.text.lower()
        assert "chatbot" not in answer.text.lower()

    # --------------------------------------------------------------------------
    # 11. Question about another employee by name (Vijay)
    # --------------------------------------------------------------------------
    def test_question_about_another_employee_by_name(self, engine):
        """Scenario: Plain name question 'What is Vijay working on?'"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")
        question = Question(
            text="What is Vijay working on?",
            context=context,
            user_id="U_AKSHAT",
        )
        answer = engine.ask(question)
        assert answer is not None
        assert "circle" in answer.text.lower()
        assert "canva" not in answer.text.lower()

    # --------------------------------------------------------------------------
    # 12. Employee work evidence isolation
    # --------------------------------------------------------------------------
    def test_employee_work_evidence_remains_isolated(self, engine):
        """Scenario: Verify evidence isolation across employees"""
        context = ConversationContext(user_id="U_AKSHAT", channel_id="C_DEV", thread_ts="")

        # Query Gurkirat
        ans_g = engine.ask(Question(
            text="What is <@U_GURKIRAT> working on?",
            context=context,
            user_id="U_AKSHAT",
        ))
        assert "canva" in ans_g.text.lower()
        assert "circle" not in ans_g.text.lower()
        assert "chatbot" not in ans_g.text.lower()
        assert "postgres" not in ans_g.text.lower()
        assert "security compliance" not in ans_g.text.lower()

        # Query Hemant
        ans_h = engine.ask(Question(
            text="What is <@U_HEMANT> working on?",
            context=context,
            user_id="U_AKSHAT",
        ))
        assert "chatbot" in ans_h.text.lower()
        assert "canva" not in ans_h.text.lower()
        assert "circle" not in ans_h.text.lower()
