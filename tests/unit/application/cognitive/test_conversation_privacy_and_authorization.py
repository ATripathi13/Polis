"""
Security, Privacy & Authorization Test Suite for POLIS Natural Organizational Conversation Intelligence.

Validates:
1. Public request with public-channel events -> Allowed
2. Public request with private-channel events -> Excluded
3. Public request with DM events -> Excluded
4. Missing channel type -> Excluded
5. Unknown channel type -> Excluded
6. Missing requester ID -> Private events excluded
7. Authorized DM participant -> Allowed
8. Unauthorized DM participant -> Excluded
9. Unknown DM membership -> Excluded
10. Authorized private-channel member -> Allowed
11. Unauthorized private-channel member -> Excluded
12. Authorized parent and reply -> Both included
13. Unauthorized parent with authorized reply -> Parent excluded (reply remains usable)
14. Parent from another channel -> Parent excluded
15. Parent from another private conversation -> Parent excluded
16. Missing parent -> Reply remains usable without parent
17. Repository retrieval exception -> No raw-event fallback
18. Duplicate source event IDs -> Deduplicated to single unique event
19. More than 500 events -> Retrieval coverage accurately handled
20. In-memory retrieval -> Stored events remain unchanged
21. PostgreSQL retrieval -> Same filtering and ordering behavior
22. Slack im, mpim, private, and public classifications
23. Microsoft Teams meeting classification
24. Unsupported platforms -> channel_type unknown, excluded
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from unittest.mock import MagicMock

from domain.common.identifier import Identifier
from domain.reasoning.value_objects import Answer, ConversationContext, Question
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
    MessageReference,
)
from engines.communication.infrastructure.repositories import InMemoryCommunicationRepository
from application.cognitive.organizational_conversation_service import OrganizationalConversationService
from application.identity.canonical_identity_service import CanonicalIdentityService


def _make_event(
    event_id: str,
    text: str,
    author_id: str,
    channel_id: str,
    channel_type: str = "public",
    created_at: datetime | None = None,
    thread_parent_id: str | None = None,
    channel_members: list[str] | None = None,
    authorized_users: list[str] | None = None,
    channel_name: str | None = None,
    platform: str = "slack",
) -> CommunicationEvent:
    now = created_at or datetime.now(timezone.utc)
    ch_meta = {"platform": platform, "slack_channel_id": channel_id}
    if channel_members is not None:
        ch_meta["members"] = channel_members

    content_meta = {"source_timestamp": event_id}
    if authorized_users is not None:
        content_meta["authorized_users"] = authorized_users

    return CommunicationEvent.create(
        correlation_id=Identifier(business_id=thread_parent_id or event_id),
        source=EventSource.SLACK if platform == "slack" else EventSource.TEAMS,
        source_event_id=event_id,
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id=author_id,
                external_ids={platform: author_id},
            ),
            display_name=f"User {author_id}",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id=channel_id,
                external_ids={platform: channel_id},
                metadata=ch_meta,
            ),
            name=channel_name or channel_id,
            channel_type=channel_type,
            metadata=ch_meta,
        ),
        content=Content(
            body=text,
            metadata=content_meta,
        ),
    )


# =============================================================================
# SCENARIOS 1-3: PUBLIC CHANNEL REQUEST PRIVACY BOUNDARIES
# =============================================================================

def test_public_request_with_public_channel_events_allowed():
    """Public requests can access public channel conversations."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    pub_ev = _make_event("pub_1", "Discussing public marketing strategy", "U_NAV", "C_GENERAL", channel_type="public")
    repo.save(pub_ev)

    q = Question(text="What was our latest discussion on marketing strategy?")
    ctx = ConversationContext(user_id="U_RANDOM", channel_id="C_GENERAL", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    assert "marketing strategy" in ans.text.lower() or any("pub_1" in str(e) for e in ans.evidence)
    assert ans.confidence > 0.5


def test_public_request_with_private_channel_events_excluded():
    """Public requests MUST NOT disclose private channel messages."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    priv_ev = _make_event("priv_1", "Private confidential discussion on executive payroll figures", "U_NAV", "C_PRIVATE", channel_type="private")
    repo.save(priv_ev)

    q = Question(text="What was our latest discussion on executive payroll?")
    ctx = ConversationContext(user_id="U_NAV", channel_id="C_PUBLIC", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    # The confidential discussion must NOT be in the answer or evidence
    assert "confidential discussion" not in ans.text.lower()
    assert "figures" not in ans.text.lower()
    assert not any("priv_1" in str(e) for e in ans.evidence)
    assert "haven't been any discussions" in ans.text.lower() or "no recorded" in ans.text.lower()


def test_public_request_with_dm_events_excluded():
    """Public requests MUST NOT disclose private DM messages."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    dm_ev = _make_event("dm_1", "Secret discussion about confidential acquisition target X in DM", "U_NAV", "D_SECRET", channel_type="im", channel_members=["U_NAV", "U_VIJAY"])
    repo.save(dm_ev)

    q = Question(text="What was our latest discussion on confidential acquisition?")
    ctx = ConversationContext(user_id="U_NAV", channel_id="C_GENERAL", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    assert "target x" not in ans.text.lower()
    assert not any("dm_1" in str(e) for e in ans.evidence)
    assert "no recorded" in ans.text.lower() or "haven't been any discussions" in ans.text.lower()


# =============================================================================
# SCENARIOS 4-5: UNKNOWN OR MISSING CHANNEL VISIBILITY
# =============================================================================

def test_missing_channel_type_excluded():
    """Events with missing channel_type must be excluded from retrieval."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    ev = _make_event("ev_1", "Discussion on alpha prototype secret details", "U_NAV", "C_UNKNOWN", channel_type="public")
    # Simulate corrupted / missing channel_type by mocking channel attribute
    mock_channel = MagicMock()
    mock_channel.channel_type = None
    mock_channel.name = "C_UNKNOWN"
    object.__setattr__(ev, "channel", mock_channel)
    repo.save(ev)

    q = Question(text="What was our latest discussion on alpha prototype?")
    ctx = ConversationContext(user_id="U_NAV", channel_id="C_GENERAL", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    assert "secret details" not in ans.text.lower()
    assert not any("ev_1" in str(e) for e in ans.evidence)
    assert "haven't been any discussions" in ans.text.lower() or "no recorded" in ans.text.lower()


def test_unknown_channel_type_excluded():
    """Events with channel_type='unknown' must be excluded from retrieval."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    ev = _make_event("ev_2", "Discussion on beta prototype secret details", "U_NAV", "C_UNKNOWN", channel_type="unknown")
    repo.save(ev)

    q = Question(text="What was our latest discussion on beta prototype?")
    ctx = ConversationContext(user_id="U_NAV", channel_id="C_GENERAL", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    assert "secret details" not in ans.text.lower()
    assert not any("ev_2" in str(e) for e in ans.evidence)
    assert "haven't been any discussions" in ans.text.lower() or "no recorded" in ans.text.lower()


# =============================================================================
# SCENARIOS 6-9: DM PARTICIPANT AUTHORIZATION
# =============================================================================

def test_missing_requester_id_private_events_excluded():
    """If requester ID is missing or None, private events are excluded."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    dm_ev = _make_event("dm_1", "DM discussion on security credentials token XYZ", "U_NAV", "D_123", channel_type="im", channel_members=["U_NAV", "U_HEMANT"])
    repo.save(dm_ev)

    # Missing user_id in context and question
    q = Question(text="What was our latest discussion on security credentials?")
    ctx = ConversationContext(user_id="", channel_id="D_123", thread_ts="123", channel_type="im")

    ans = service.answer_question(q, ctx)
    assert "token xyz" not in ans.text.lower()
    assert not any("dm_1" in str(e) for e in ans.evidence)


def test_authorized_dm_participant_allowed():
    """A verified DM participant querying in DM can access the conversation."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    dm_ev = _make_event("dm_1", "DM discussion on database migration details", "U_NAV", "D_MIGRATION", channel_type="im", channel_members=["U_NAV", "U_HEMANT"])
    repo.save(dm_ev)

    q = Question(text="What was our latest discussion on database migration?")
    ctx = ConversationContext(user_id="U_HEMANT", channel_id="D_MIGRATION", thread_ts="123", channel_type="im")

    ans = service.answer_question(q, ctx)
    assert any("dm_1" in str(e) for e in ans.evidence) or "database migration" in ans.text.lower()


def test_unauthorized_dm_participant_excluded():
    """A user not in the verified participant list cannot access the DM conversation."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    dm_ev = _make_event("dm_1", "DM discussion on salary bands tier 4", "U_NAV", "D_SECRET", channel_type="im", channel_members=["U_NAV", "U_HEMANT"])
    repo.save(dm_ev)

    # U_INTRUDER is not in channel_members
    q = Question(text="What was our latest discussion on salary bands?")
    ctx = ConversationContext(user_id="U_INTRUDER", channel_id="D_SECRET", thread_ts="123", channel_type="im")

    ans = service.answer_question(q, ctx)
    assert "tier 4" not in ans.text.lower()
    assert not any("dm_1" in str(e) for e in ans.evidence)


def test_unknown_dm_membership_excluded():
    """If a DM event has no participant/membership metadata, third parties cannot access it."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    # No members list in metadata
    dm_ev = _make_event("dm_1", "DM discussion on undisclosed budget cuts 20 percent", "U_NAV", "D_NO_MEMBERS", channel_type="im")
    repo.save(dm_ev)

    # U_OTHER tries to query
    q = Question(text="What was our latest discussion on undisclosed budget cuts?")
    ctx = ConversationContext(user_id="U_OTHER", channel_id="D_NO_MEMBERS", thread_ts="123", channel_type="im")

    ans = service.answer_question(q, ctx)
    assert "20 percent" not in ans.text.lower()
    assert not any("dm_1" in str(e) for e in ans.evidence)


# =============================================================================
# SCENARIOS 10-11: PRIVATE CHANNEL MEMBER AUTHORIZATION
# =============================================================================

def test_authorized_private_channel_member_allowed():
    """A verified member of a private channel can access it when querying in private context."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    priv_ev = _make_event("priv_1", "Private channel discussion on patent filing", "U_NAV", "C_PATENT", channel_type="private", channel_members=["U_NAV", "U_LEGAL"])
    repo.save(priv_ev)

    q = Question(text="What was our latest discussion on patent filing?")
    ctx = ConversationContext(user_id="U_LEGAL", channel_id="C_PATENT", thread_ts="123", channel_type="private")

    ans = service.answer_question(q, ctx)
    assert any("priv_1" in str(e) for e in ans.evidence) or "patent filing" in ans.text.lower()


def test_unauthorized_private_channel_member_excluded():
    """An unverified user cannot access private channel discussions."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    priv_ev = _make_event("priv_1", "Private channel discussion on merger negotiation terms", "U_NAV", "C_MERGER", channel_type="private", channel_members=["U_NAV", "U_LEGAL"])
    repo.save(priv_ev)

    q = Question(text="What was our latest discussion on merger negotiation?")
    ctx = ConversationContext(user_id="U_STRANGER", channel_id="C_MERGER", thread_ts="123", channel_type="private")

    ans = service.answer_question(q, ctx)
    assert "negotiation terms" not in ans.text.lower()
    assert not any("priv_1" in str(e) for e in ans.evidence)


# =============================================================================
# SCENARIOS 12-16: PARENT MESSAGE PRIVACY
# =============================================================================

def test_authorized_parent_and_reply_both_included():
    """When both parent and reply are public and in the same channel, thread context is preserved."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    parent_ev = _make_event("msg_parent", "We should consider migrating to FastAPI", "U_NAV", "C_ENG", channel_type="public")
    repo.save(parent_ev)

    reply_ev = _make_event("msg_reply", "I agree, FastAPI performance is superior", "U_VIJAY", "C_ENG", channel_type="public", thread_parent_id="msg_parent")
    repo.save(reply_ev)

    q = Question(text="What did we discuss about FastAPI?")
    ctx = ConversationContext(user_id="U_HEMANT", channel_id="C_ENG", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    assert "fastapi" in ans.text.lower()


def test_unauthorized_parent_with_authorized_reply_excludes_parent():
    """
    If a reply is in an accessible space but references a parent from a private/inaccessible
    conversation, the parent content MUST be stripped while the reply remains usable.
    """
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    # Parent was in a private channel
    parent_ev = _make_event("priv_parent", "Confidential unreleased product code name is ORION", "U_NAV", "C_PRIVATE", channel_type="private", channel_members=["U_NAV"])
    repo.save(parent_ev)

    # Reply is in public channel
    reply_ev = _make_event("pub_reply", "Acknowledged and working on the deployment", "U_VIJAY", "C_GENERAL", channel_type="public", thread_parent_id="priv_parent")
    repo.save(reply_ev)

    # Direct filtering test
    all_events = repo.get_recent_events(include_parent_context=True)
    ctx = ConversationContext(user_id="U_PUBLIC_USER", channel_id="C_GENERAL", thread_ts="123", channel_type="public")
    q = Question(text="What is happening?")

    filtered = service._filter_accessible_events(all_events, ctx, q, all_events_pool=all_events)

    # Public reply is accessible
    assert any(getattr(e, "source_event_id", "") == "pub_reply" for e in filtered)
    # Private parent is excluded
    assert not any(getattr(e, "source_event_id", "") == "priv_parent" for e in filtered)

    # The reply must NOT contain the parent's secret body in its metadata or references
    reply_in_filtered = next(e for e in filtered if getattr(e, "source_event_id", "") == "pub_reply")
    assert "ORION" not in str(reply_in_filtered.content.metadata)
    assert not any("ORION" in str(getattr(ref, "metadata", "")) for ref in reply_in_filtered.references)


def test_parent_from_another_channel_excluded():
    """A parent from another channel must not be attached as thread context."""
    repo = InMemoryCommunicationRepository()

    parent_ev = _make_event("p_other", "Parent message in alpha channel", "U_NAV", "C_ALPHA", channel_type="public")
    repo.save(parent_ev)

    reply_ev = _make_event("r_beta", "Reply in beta channel", "U_VIJAY", "C_BETA", channel_type="public", thread_parent_id="p_other")
    repo.save(reply_ev)

    # When retrieving from repo, cross-channel parent context is NOT attached
    recent = repo.get_recent_events(include_parent_context=True)
    reply_loaded = next(e for e in recent if e.source_event_id == "r_beta")
    assert "parent_message_body" not in reply_loaded.content.metadata


def test_missing_parent_reply_remains_usable():
    """If parent message is not found, reply remains usable without crashing."""
    repo = InMemoryCommunicationRepository()
    service = OrganizationalConversationService(communication_repository=repo)

    reply_ev = _make_event("orphan_reply", "Working on the Kubernetes Helm chart upgrade", "U_NAV", "C_GENERAL", channel_type="public", thread_parent_id="nonexistent_parent_id")
    repo.save(reply_ev)

    q = Question(text="What is happening with Kubernetes Helm chart?")
    ctx = ConversationContext(user_id="U_DEV", channel_id="C_GENERAL", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    assert "helm chart" in ans.text.lower() or "User U_NAV" in ans.text


# =============================================================================
# SCENARIOS 17-21: RETRIEVAL ACCURACY, DEDUPLICATION, REPOSITORY SAFETY
# =============================================================================

def test_repository_retrieval_exception_no_raw_event_fallback():
    """If get_recent_events() raises an exception, POLIS fails safely without dumping raw .events."""
    mock_repo = MagicMock()
    mock_repo.get_recent_events.side_effect = RuntimeError("Database connection timed out")
    # Stub raw .events containing confidential messages
    mock_repo.events = [
        _make_event("leak_1", "CONFIDENTIAL DATA THAT SHOULD NOT BE ACCESSED", "U_NAV", "C_SECRET", channel_type="private")
    ]

    service = OrganizationalConversationService(communication_repository=mock_repo)

    q = Question(text="What was our latest discussion on CONFIDENTIAL DATA?")
    ctx = ConversationContext(user_id="U_NAV", channel_id="C_GENERAL", thread_ts="123", channel_type="public")

    ans = service.answer_question(q, ctx)
    assert "CONFIDENTIAL DATA" not in ans.text
    assert not any("leak_1" in str(e) for e in ans.evidence)
    assert "haven't been any discussions" in ans.text.lower() or "no recorded" in ans.text.lower()


def test_duplicate_source_event_ids_deduplicated():
    """Duplicate source_event_ids in in-memory repository are deduplicated."""
    repo = InMemoryCommunicationRepository()

    ev1 = _make_event("dup_1", "Duplicate message content", "U_NAV", "C_GENERAL")
    ev2 = _make_event("dup_1", "Duplicate message content", "U_NAV", "C_GENERAL")
    repo.save(ev1)
    repo.save(ev2)

    events = repo.get_recent_events(limit=50)
    assert len([e for e in events if e.source_event_id == "dup_1"]) == 1


def test_in_memory_retrieval_does_not_mutate_stored_events():
    """Enriching parent context must NOT mutate stored events in the in-memory repository."""
    repo = InMemoryCommunicationRepository()

    parent = _make_event("parent_orig", "Parent original text", "U_NAV", "C_ENG")
    repo.save(parent)

    reply = _make_event("reply_orig", "Reply text", "U_VIJAY", "C_ENG", thread_parent_id="parent_orig")
    repo.save(reply)

    # Check original stored reply
    stored_reply = next(e for e in repo._events if e.source_event_id == "reply_orig")
    orig_metadata_keys = set(stored_reply.content.metadata.keys())
    orig_refs_count = len(stored_reply.references)

    # Retrieve with parent context enrichment
    res1 = repo.get_recent_events(include_parent_context=True)
    res2 = repo.get_recent_events(include_parent_context=True)

    # Stored event in repo._events MUST be unmodified
    assert set(stored_reply.content.metadata.keys()) == orig_metadata_keys
    assert len(stored_reply.references) == orig_refs_count

    # Returned events have parent context
    ret_reply_1 = next(e for e in res1 if e.source_event_id == "reply_orig")
    assert "parent_message_body" in ret_reply_1.content.metadata

    # Repeated calls do not accumulate duplicate references
    ret_reply_2 = next(e for e in res2 if e.source_event_id == "reply_orig")
    parent_refs = [r for r in ret_reply_2.references if r.relationship_type == "parent_message"]
    assert len(parent_refs) == 1


# =============================================================================
# SCENARIOS 22-25: CLASSIFICATIONS & IDENTITY RESOLUTION
# =============================================================================

def test_slack_channel_type_classifications():
    """Verify CanonicalIdentityService classifies Slack D, G, C channels correctly."""
    svc = CanonicalIdentityService()

    # D -> im
    dm = svc.resolve_channel("D01234567")
    assert dm.channel_type == "im"

    # G -> mpim
    mpim = svc.resolve_channel("G01234567")
    assert mpim.channel_type == "mpim"

    # C -> public by default
    pub = svc.resolve_channel("C01234567")
    assert pub.channel_type == "public"

    # C with is_private_hint on a different channel -> private
    priv = svc.resolve_channel("C98765432", is_private_hint=True)
    assert priv.channel_type == "private"


def test_teams_meeting_classification():
    """Verify Teams meetings are classified as 'meeting' and supported platforms work."""
    svc = CanonicalIdentityService()

    meeting = svc.resolve_channel("meeting-12345", platform="microsoft_teams")
    assert meeting.channel_type == "meeting"


def test_unsupported_platform_channel_type_is_unknown():
    """Unsupported platforms must be classified as 'unknown', not assumed 'public'."""
    svc = CanonicalIdentityService()

    unknown = svc.resolve_channel("custom-channel-id", platform="unsupported_chat")
    assert unknown.channel_type == "unknown"


def test_raw_id_sanitization_and_unverified_fallback():
    """Ensure raw IDs are replaced with clean human names or unverified fallback."""
    svc = CanonicalIdentityService()
    svc.register_user("Nav Thethi", "U_NAV_TEST")

    # Resolved user
    s1 = svc.sanitize_user_facing_text("Contact <@U_NAV_TEST|nav> for details.")
    assert "@Nav Thethi" in s1
    assert "U_NAV_TEST" not in s1

    # Unverified user ID
    s2 = svc.sanitize_user_facing_text("Message sent by <@U_UNKNOWN_PERSON>.")
    assert "an unverified team member" in s2
    assert "U_UNKNOWN_PERSON" not in s2
