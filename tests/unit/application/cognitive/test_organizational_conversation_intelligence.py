"""
Unit and integration tests for Natural Organizational Conversation Intelligence in POLIS.

Tests:
1. "What was our latest discussion on IVAN?" -> Truthful absence, no raw IDs.
2. "What is everyone currently working on?" -> Team-wide aggregation; extracts active work across team members; never treats "everyone" as a person; no raw IDs.
3. "What decisions have we made about marketing automation?" -> Extracts decisions from discussions, distinguishes from suggestions; no raw IDs.
4. "Who is handling the website changes?" -> Extracts explicit owner/assignee from evidence, not passive mentions.
5. "What did we discuss about the LinkedIn automation?" -> Extracts LinkedIn discussions from actual evidence.
6. "What is the latest update from Hemant and Vijay?" -> Extracts updates for both people, dynamic synthesis.
7. "Where can I find the discussion about this?" -> Provides source channel #agentic-army and date context.
8. Newer updates superseding older ones (recency over keyword count).
9. Identity Resolution and Separation: Unknown user/channel formatted as 'an unverified team member' / 'an unverified channel'; never leaks raw IDs.
10. Raw ID Sanitization: All mentions (<@U...>, <#C...>) and bare IDs (U..., C...) replaced.
11. CognitivePlanner routing: Correct intents and parameters for topic and team queries.
12. SimpleCognitiveEngine end-to-end orchestration: ask() routes seamlessly to organizational intelligence.
13. LLM synthesis path: Prompt contains resolved names, dates, and channels, with sanitized output.
14. Public-channel vs DM consistency: Private DM messages are NEVER disclosed to a public channel query; in DM context, authorized private messages are included.
15. Zero hardcoded narratives: Verifies dynamic synthesis for novel/arbitrary topics and participants.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from application.cognitive import (
    CognitivePlanner,
    OrganizationalConversationService,
    SimpleCognitiveEngine,
)
from application.identity import CanonicalIdentityService
from domain.common.identifier import Identifier
from domain.operations import (
    InMemoryOperationalItemRepository,
    OperationalItem,
    OperationalItemType,
)
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


def _build_event(
    event_id: str,
    text: str,
    actor_id: str,
    actor_name: str,
    channel_id: str = "C0BBMKRD4R4",
    channel_name: str = "agentic-army",
    channel_type: str = "public",
    created_at: datetime | None = None,
    correlation_id: str | None = None,
) -> CommunicationEvent:
    """Helper to build a domain CommunicationEvent."""
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
        ),
    )
    ev.created_at = created_at or datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
    return ev


@pytest.fixture
def identity_service() -> CanonicalIdentityService:
    """CanonicalIdentityService pre-populated with workspace entities."""
    svc = CanonicalIdentityService()
    svc.register_channel("C0BBMKRD4R4", "agentic-army")
    svc.register_channel("C0BG7NWMD6D", "agentic-army")
    svc.register_channel("C0C3BGUGAFK", "testing")
    svc.register_user(canonical_name="Nav Thethi", platform_user_id="U0BBHB87SJF")
    svc.register_user(canonical_name="Hemant Kumar Sah", platform_user_id="U0BU41F6CTD")
    svc.register_user(canonical_name="Vijay", platform_user_id="U0BMLJD003G")
    svc.register_user(canonical_name="Akshat", platform_user_id="U0BB8T4BVEK")
    svc.register_user(canonical_name="Gurkirat Singh", platform_user_id="U0BBPU6400M")
    return svc


@pytest.fixture
def populated_comm_repo() -> InMemoryCommunicationRepository:
    """Repository containing realistic September 18-21 discussions."""
    repo = InMemoryCommunicationRepository()
    sept18 = datetime(2026, 9, 18, 12, 30, 0, tzinfo=timezone.utc)
    sept21 = datetime(2026, 9, 21, 14, 0, 0, tzinfo=timezone.utc)

    # Automation thread in C0BBMKRD4R4 (#agentic-army)
    repo.save(_build_event(
        "ev_nav_1",
        "Hi Hemant Kumar Sah, you have been added to the sub account and given access to Form Builder "
        "(Forms -> View & manage). Please do not create any new fields or forms without discussing first.",
        actor_id="U0BBHB87SJF",
        actor_name="Nav Thethi",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=sept18,
        correlation_id="thread_automation",
    ))
    repo.save(_build_event(
        "ev_hemant_1",
        "Configured the backend with the GHL Private Integration Token. Now testing the webhook to update "
        "anonymous contacts with Form 4 submission details.",
        actor_id="U0BU41F6CTD",
        actor_name="Hemant Kumar Sah",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=sept18,
        correlation_id="thread_automation",
    ))
    repo.save(_build_event(
        "ev_vijay_1",
        "Working on testing the OTP verification workflow end-to-end to address issues identified during testing.",
        actor_id="U0BMLJD003G",
        actor_name="Vijay",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=sept18,
        correlation_id="thread_automation",
    ))
    repo.save(_build_event(
        "ev_nav_2",
        "Confirmed SMS OTP delivery is working via Twilio for test numbers.",
        actor_id="U0BBHB87SJF",
        actor_name="Nav Thethi",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=sept18,
        correlation_id="thread_automation",
    ))

    # Website updates in C0BG7NWMD6D (#agentic-army)
    repo.save(_build_event(
        "ev_web_1",
        "Akshat is handling the website changes for the landing page and navigation redesign.",
        actor_id="U0BBHB87SJF",
        actor_name="Nav Thethi",
        channel_id="C0BG7NWMD6D",
        channel_name="agentic-army",
        created_at=sept18 + timedelta(hours=1),
    ))
    repo.save(_build_event(
        "ev_web_2",
        "Working on website changes: updating hero copy and SEO metadata.",
        actor_id="U0BB8T4BVEK",
        actor_name="Akshat",
        channel_id="C0BG7NWMD6D",
        channel_name="agentic-army",
        created_at=sept18 + timedelta(hours=2),
    ))

    # LinkedIn automation thread in C0BBMKRD4R4
    repo.save(_build_event(
        "ev_li_1",
        "We agreed to use the LinkedIn automation script to connect with leads.",
        actor_id="U0BBHB87SJF",
        actor_name="Nav Thethi",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=sept18 + timedelta(hours=3),
    ))
    repo.save(_build_event(
        "ev_li_2",
        "Working on LinkedIn automation connector and rate limiting safeguards.",
        actor_id="U0BU41F6CTD",
        actor_name="Hemant Kumar Sah",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=sept18 + timedelta(hours=4),
    ))

    # Akshat marketing & test updates in C0BG7NWMD6D and C0C3BGUGAFK
    repo.save(_build_event(
        "ev_akshat_1",
        "Working on the Publishing Calendar and organizing content topics for next week.",
        actor_id="U0BB8T4BVEK",
        actor_name="Akshat",
        channel_id="C0BG7NWMD6D",
        channel_name="agentic-army",
        created_at=sept18,
    ))
    repo.save(_build_event(
        "ev_akshat_2",
        "Working on Polis test documentation. Gurkirat is working on topics today.",
        actor_id="U0BB8T4BVEK",
        actor_name="Akshat",
        channel_id="C0C3BGUGAFK",
        channel_name="testing",
        created_at=sept21,
    ))
    return repo


# =============================================================================
# SCENARIO 1: IVAN DISCUSSION QUERY
# =============================================================================

def test_ivan_query_truthful_absence_no_raw_ids(populated_comm_repo, identity_service):
    """Querying about IVAN returns a truthful explanation that no Slack discussions exist, without leaking raw IDs."""
    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
    )

    q = Question(text="What was our latest discussion on IVAN?")
    ans = service.answer_question(q)

    assert ans is not None
    assert ans.is_conversational is True
    text_lower = ans.text.lower()

    # Truthful absence
    assert "ivan" in text_lower
    assert any(phrase in text_lower for phrase in [
        "haven't been any discussions",
        "no recorded",
        "no discussions",
        "haven't been any team discussions",
    ])

    # Strict identity separation: NO raw Slack IDs allowed in user-facing answer
    assert "U0" not in ans.text
    assert "C0" not in ans.text
    assert "<@" not in ans.text
    assert "<#" not in ans.text


# =============================================================================
# SCENARIO 2: TEAM-WIDE WORK AGGREGATION ("What is everyone working on?")
# =============================================================================

def test_team_work_aggregation_everyone(populated_comm_repo, identity_service):
    """What is everyone currently working on aggregates work across all active members without treating 'everyone' as a person."""
    ops_repo = InMemoryOperationalItemRepository()
    ops_repo.save(OperationalItem(
        identifier=Identifier(business_id="task_akshat_1"),
        item_type=OperationalItemType.TASK,
        summary="Complete Q3 roadmap review",
        owner_id="U0BB8T4BVEK",
        owner_name="Akshat",
    ))

    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
        operational_item_repository=ops_repo,
    )

    q = Question(text="What is everyone currently working on?")
    ans = service.answer_question(q)

    assert ans is not None
    text = ans.text

    # All active team members are included
    assert "Hemant Kumar Sah" in text or "Hemant" in text
    assert "Vijay" in text
    assert "Akshat" in text
    assert "Nav Thethi" in text or "Nav" in text

    # Gurkirat included via attribution in communication
    assert "Gurkirat" in text

    # Asserts that 'everyone' is not listed as a person
    assert "**everyone**" not in text.lower()
    assert "• **everyone**" not in text.lower()

    # Operational task included
    assert "roadmap" in text.lower() or "q3" in text.lower()

    # Strict identity separation
    assert "U0" not in text
    assert "C0" not in text


# =============================================================================
# SCENARIO 3: DECISIONS QUERY ("What decisions have we made about marketing automation?")
# =============================================================================

def test_marketing_automation_decisions(populated_comm_repo, identity_service):
    """What decisions have we made about marketing automation extracts agreed decisions and constraints."""
    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
    )

    q = Question(text="What decisions have we made about marketing automation?")
    ans = service.answer_question(q)

    assert ans is not None
    text = ans.text

    # Captures decisions dynamically from events (Nav granting access, instructions not to create new fields without discussion)
    assert "Nav Thethi" in text or "Nav" in text
    assert "sub account" in text.lower() or "form builder" in text.lower() or "access" in text.lower()
    assert "#agentic-army" in text

    # Strict identity separation
    assert "U0" not in text
    assert "C0" not in text


# =============================================================================
# SCENARIO 4: WORK OWNERSHIP QUERY ("Who is handling the website changes?")
# =============================================================================

def test_who_is_handling_website_changes(populated_comm_repo, identity_service):
    """Who is handling the website changes identifies Akshat from actual communication evidence."""
    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
    )

    q = Question(text="Who is handling the website changes?")
    ans = service.answer_question(q)

    assert ans is not None
    text = ans.text

    # Identifies Akshat as the person working on / handling website changes
    assert "Akshat" in text
    assert "website" in text.lower()
    assert "#agentic-army" in text

    # Zero raw IDs
    assert "U0" not in text
    assert "C0" not in text


# =============================================================================
# SCENARIO 5: TOPIC DISCUSSION QUERY ("What did we discuss about the LinkedIn automation?")
# =============================================================================

def test_linkedin_automation_discussion(populated_comm_repo, identity_service):
    """What did we discuss about the LinkedIn automation extracts discussion dynamically from events."""
    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
    )

    q = Question(text="What did we discuss about the LinkedIn automation?")
    ans = service.answer_question(q)

    assert ans is not None
    text = ans.text

    assert "LinkedIn" in text or "linkedin" in text.lower()
    assert "Hemant" in text or "Nav" in text
    assert "#agentic-army" in text

    # Zero raw IDs
    assert "U0" not in text
    assert "C0" not in text


# =============================================================================
# SCENARIO 6: MULTI-PERSON UPDATE QUERY ("What is the latest update from Hemant and Vijay?")
# =============================================================================

def test_latest_update_from_hemant_and_vijay(populated_comm_repo, identity_service):
    """What is the latest update from Hemant and Vijay extracts updates for both people dynamically."""
    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
    )

    q = Question(text="What is the latest update from Hemant and Vijay?")
    ans = service.answer_question(q)

    assert ans is not None
    text = ans.text

    assert "Hemant" in text
    assert "Vijay" in text
    assert "#agentic-army" in text
    assert "September" in text or "Sept" in text

    # Zero raw IDs
    assert "U0" not in text
    assert "C0" not in text


# =============================================================================
# SCENARIO 7: LOCATION QUERY ("Where can I find the discussion about this?")
# =============================================================================

def test_where_can_i_find_the_discussion(populated_comm_repo, identity_service):
    """Where can I find the discussion about marketing automation identifies #agentic-army."""
    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
    )

    q = Question(text="Where can I find the discussion about marketing automation?")
    ans = service.answer_question(q)

    assert ans is not None
    text = ans.text

    assert "#agentic-army" in text
    assert "September" in text or "Sept" in text
    assert "C0BBMKRD4R4" not in text


# =============================================================================
# SCENARIO 8: RECENCY OVERRIDE (Newer updates supersede older information)
# =============================================================================

def test_newer_updates_supersede_older_information(identity_service):
    """A newer update stating work is completed takes precedence over an older message stating it is in progress."""
    repo = InMemoryCommunicationRepository()
    t_old = datetime(2026, 9, 10, 10, 0, 0, tzinfo=timezone.utc)
    t_new = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)

    # Older message with repeated keywords
    repo.save(_build_event(
        "ev_old_1",
        "Working on the payment gateway integration. In progress, testing payment gateway API, payment gateway webhook.",
        actor_id="U0BU41F6CTD",
        actor_name="Hemant Kumar Sah",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=t_old,
    ))
    # Newer update stating completion
    repo.save(_build_event(
        "ev_new_1",
        "Confirmed payment gateway integration is completed, fully verified and deployed.",
        actor_id="U0BU41F6CTD",
        actor_name="Hemant Kumar Sah",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=t_new,
    ))

    service = OrganizationalConversationService(
        communication_repository=repo,
        identity_service=identity_service,
    )

    q = Question(text="Where do things stand with the payment gateway?")
    ans = service.answer_question(q)

    assert ans is not None
    # Prioritizes the latest status (September 15, completed)
    assert "September 15" in ans.text
    assert "completed" in ans.text.lower() or "verified" in ans.text.lower()
    assert "U0" not in ans.text


# =============================================================================
# SCENARIO 9: UNVERIFIED IDENTITIES COMMUNICATED HONESTLY
# =============================================================================

def test_identity_separation_and_unverified_handling():
    """Unmapped Slack IDs are communicated as 'an unverified team member' and 'an unverified channel', never leaking raw IDs."""
    repo = InMemoryCommunicationRepository()
    svc = CanonicalIdentityService()

    repo.save(_build_event(
        "ev_unknown_1",
        "Working on the mystery project backend.",
        actor_id="U999999999",
        actor_name="Ghost User",
        channel_id="C999999999",
        channel_name="secret-room",
    ))

    org_service = OrganizationalConversationService(
        communication_repository=repo,
        identity_service=svc,
    )

    ans = org_service.answer_question(Question(text="What is everyone currently working on?"))
    assert ans is not None

    # Never exposes raw ID
    assert "U999999999" not in ans.text
    assert "C999999999" not in ans.text

    # Communicates as unverified
    assert "an unverified team member" in ans.text


# =============================================================================
# SCENARIO 10: RAW ID SANITIZATION IN USER-FACING RESPONSE
# =============================================================================

def test_raw_id_sanitization_in_user_facing_response(identity_service):
    """Sanitize helper replaces mentions and bare IDs with resolved names or unverified notices."""
    raw_text = (
        "Hey <@U0BU41F6CTD|hemant>, check <#C0BBMKRD4R4|agentic-army>. "
        "Also U0BMLJD003G and U999999999 are in C0BG7NWMD6D and C999999999."
    )

    sanitized = identity_service.sanitize_user_facing_text(raw_text)

    # Resolved replacements
    assert "@Hemant Kumar Sah" in sanitized or "Hemant Kumar Sah" in sanitized
    assert "#agentic-army" in sanitized
    assert "Vijay" in sanitized

    # Unverified replacements
    assert "an unverified team member" in sanitized
    assert "an unverified channel" in sanitized

    # No raw IDs remain
    assert "U0BU41F6CTD" not in sanitized
    assert "C0BBMKRD4R4" not in sanitized
    assert "U0BMLJD003G" not in sanitized
    assert "U999999999" not in sanitized
    assert "C999999999" not in sanitized


# =============================================================================
# SCENARIO 11: PLANNER QUERY ROUTING
# =============================================================================

def test_planner_routes_organizational_questions(identity_service):
    """CognitivePlanner classifies organizational questions into HISTORICAL_DISCUSSION or team-scope EMPLOYEE_WORK_QUERY."""
    planner = CognitivePlanner(identity_service=identity_service)

    p1 = planner.plan(Question(text="What was our latest discussion on IVAN?"))
    assert p1.intent == IntentCategory.HISTORICAL_DISCUSSION

    p2 = planner.plan(Question(text="What decisions have we made about marketing automation?"))
    assert p2.intent == IntentCategory.HISTORICAL_DISCUSSION

    p3 = planner.plan(Question(text="Who is handling the website changes?"))
    assert p3.intent == IntentCategory.HISTORICAL_DISCUSSION

    p4 = planner.plan(Question(text="What did we discuss about the LinkedIn automation?"))
    assert p4.intent == IntentCategory.HISTORICAL_DISCUSSION

    p5 = planner.plan(Question(text="What is the latest update from Hemant and Vijay?"))
    assert p5.intent == IntentCategory.HISTORICAL_DISCUSSION

    p6 = planner.plan(Question(text="Where can I find the discussion about marketing automation?"))
    assert p6.intent == IntentCategory.HISTORICAL_DISCUSSION

    p7 = planner.plan(Question(text="What is everyone currently working on?"))
    assert p7.intent == IntentCategory.EMPLOYEE_WORK_QUERY
    assert p7.entities.extra_params.get("scope") == "team"
    assert "everyone" not in (p7.entities.target_user_name or "").lower()


# =============================================================================
# SCENARIO 12: SIMPLE COGNITIVE ENGINE END-TO-END ASK() ROUTING
# =============================================================================

def test_cognitive_engine_end_to_end_ask_routing(populated_comm_repo, identity_service):
    """SimpleCognitiveEngine.ask() correctly routes topic questions and team questions through OrganizationalConversationService."""
    pipeline = MagicMock()
    qa = MagicMock()
    planner = CognitivePlanner(identity_service=identity_service)

    org_service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
    )

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        planner=planner,
        identity_resolver=identity_service,
        organizational_conversation_service=org_service,
    )

    # Topic query
    ans_topic = engine.ask(Question(text="What was our latest discussion on IVAN?"))
    assert ans_topic is not None
    assert "ivan" in ans_topic.text.lower()
    assert "U0" not in ans_topic.text
    assert "C0" not in ans_topic.text

    # Team query
    ans_team = engine.ask(Question(text="What is everyone currently working on?"))
    assert ans_team is not None
    assert "Hemant" in ans_team.text
    assert "Vijay" in ans_team.text
    assert "Akshat" in ans_team.text
    assert "U0" not in ans_team.text
    assert "C0" not in ans_team.text


# =============================================================================
# SCENARIO 13: LLM SYNTHESIS PATH AND PROMPT GROUNDING
# =============================================================================

def test_llm_synthesis_path_and_prompt_grounding(populated_comm_repo, identity_service):
    """When LLM is provided, prompt includes resolved names, channels, dates, and sanitized output is returned."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = (
        "Back on September 18 in #agentic-army, Hemant Kumar Sah and Vijay were working on the GHL webhook "
        "and OTP verification, while Nav Thethi coordinated permissions."
    )

    service = OrganizationalConversationService(
        communication_repository=populated_comm_repo,
        identity_service=identity_service,
        llm_client=mock_llm,
    )

    q = Question(text="Where do things stand with the automation project?")
    ans = service.answer_question(q)

    assert mock_llm.generate.called
    call_args = mock_llm.generate.call_args[0][0]

    assert "Hemant Kumar Sah" in call_args
    assert "#agentic-army" in call_args
    assert "U0BU41F6CTD" not in call_args
    assert "C0BBMKRD4R4" not in call_args

    assert "September 18" in ans.text
    assert "Hemant Kumar Sah" in ans.text
    assert "#agentic-army" in ans.text
    assert "U0" not in ans.text


# =============================================================================
# SCENARIO 14: PUBLIC-CHANNEL VS DM CONSISTENCY AND PRIVACY BOUNDARIES
# =============================================================================

def test_public_channel_does_not_disclose_private_dm_messages(identity_service):
    """Private DM messages are never disclosed in public channels; in DM context, authorized private messages are included."""
    repo = InMemoryCommunicationRepository()
    t = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)

    # Public message about marketing calendar
    repo.save(_build_event(
        "ev_pub_1",
        "Publishing calendar is scheduled for review.",
        actor_id="U0BB8T4BVEK",
        actor_name="Akshat",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        channel_type="public",
        created_at=t,
    ))

    # Confidential DM message between Nav and Hemant
    repo.save(_build_event(
        "ev_priv_1",
        "Confidential compensation review discussion for leadership.",
        actor_id="U0BBHB87SJF",
        actor_name="Nav Thethi",
        channel_id="D_CONFIDENTIAL_1",
        channel_name="dm-nav-hemant",
        channel_type="im",
        created_at=t + timedelta(minutes=5),
    ))

    service = OrganizationalConversationService(
        communication_repository=repo,
        identity_service=identity_service,
    )

    # 1. Requester asks in a PUBLIC channel
    pub_ctx = ConversationContext(channel_id="C0BBMKRD4R4", thread_ts="100.1", user_id="U0BB8T4BVEK", channel_type="channel")
    q_pub = Question(text="What was our latest discussion on compensation?", context=pub_ctx)
    ans_pub = service.answer_question(q_pub, pub_ctx)

    # Must NOT disclose the private compensation DM in public channel!
    assert "confidential compensation review" not in ans_pub.text.lower()
    assert "there haven't been any discussions" in ans_pub.text.lower()

    # 2. Requester (Nav) asks in a DM where they ARE authorized
    dm_ctx = ConversationContext(channel_id="D_CONFIDENTIAL_1", thread_ts="100.2", user_id="U0BBHB87SJF", channel_type="im")
    q_dm = Question(text="What was our latest discussion on compensation?", context=dm_ctx)
    ans_dm = service.answer_question(q_dm, dm_ctx)

    # Nav is authorized, so the information is accessible in their private DM
    assert "compensation" in ans_dm.text.lower()
    assert "Nav Thethi" in ans_dm.text


# =============================================================================
# SCENARIO 15: ZERO HARDCODED NARRATIVES (Arbitrary Topic Grounding)
# =============================================================================

def test_zero_hardcoded_narratives_arbitrary_topic(identity_service):
    """Novel topic with arbitrary names is synthesized accurately from evidence with zero hardcoded narrative."""
    repo = InMemoryCommunicationRepository()
    t = datetime(2026, 9, 25, 15, 0, 0, tzinfo=timezone.utc)

    repo.save(_build_event(
        "ev_novel_1",
        "Agreed to migrate PostgreSQL metrics to Prometheus exporter next sprint.",
        actor_id="U0BU41F6CTD",
        actor_name="Hemant Kumar Sah",
        channel_id="C0BBMKRD4R4",
        channel_name="agentic-army",
        created_at=t,
    ))

    service = OrganizationalConversationService(
        communication_repository=repo,
        identity_service=identity_service,
    )

    q = Question(text="What did we discuss about PostgreSQL metrics?")
    ans = service.answer_question(q)

    assert ans is not None
    text = ans.text

    # Dynamically generated from the novel message text
    assert "Hemant Kumar Sah" in text
    assert "Prometheus" in text
    assert "September 25" in text
    assert "#agentic-army" in text
    assert "U0" not in text
    assert "C0" not in text
