"""
Regression tests for Phase 2: Calendar Agent identity and display-name leaks.

Verifies:
1. Resolution of both <@U...> mentions and raw Slack IDs.
2. Safe behavior when identity lookup fails (no raw IDs in display fields).
3. Resolved names in scheduling confirmations.
4. Unresolved audiences without raw IDs in responses.
5. Persistence and backward compatibility of audience_display_name.
6. Reminder status with resolved and unresolved recipients (no raw IDs in backticks).
7. Individual-audience inspection.
8. Preservation of internal IDs for technical operations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from domain.calendar import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntry,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderPolicy,
    InMemoryCalendarRepository,
)
from application.calendar.audience_resolution_service import (
    AudienceResolutionService,
    SlackMembershipDirectoryProvider,
)
from application.calendar.calendar_agent import CalendarAgent
from application.calendar.calendar_service import CalendarService


class MockIdentityService:
    """Mock identity service providing display names and user objects."""

    def __init__(self, names: dict[str, str] | None = None, failing_ids: set[str] | None = None) -> None:
        self.names = names or {}
        self.failing_ids = failing_ids or set()

    def get_display_name(self, user_id: str) -> str:
        if user_id in self.failing_ids:
            raise RuntimeError(f"Slack API error for user {user_id}")
        return self.names.get(user_id, user_id)

    def resolve_user(self, name_or_id: str) -> dict | None:
        if name_or_id in self.failing_ids:
            raise RuntimeError(f"Slack API error resolving {name_or_id}")
        if name_or_id in self.names:
            return {
                "id": name_or_id,
                "name": self.names[name_or_id],
                "real_name": self.names[name_or_id],
            }
        for uid, name in self.names.items():
            if name.lower() == name_or_id.lower():
                return {"id": uid, "name": name, "real_name": name}
        return None

    def get_user_id(self, user: dict | None) -> str | None:
        return user.get("id") if user else None


@pytest.fixture
def identity_service() -> MockIdentityService:
    return MockIdentityService(
        names={
            "U0BU14F6CTD": "Hemant Kumar Sah",
            "U0123456789": "Alice Wonderland",
            "U_CREATOR": "Meeting Organizer",
        },
        failing_ids={"U_FAILING_ID"},
    )


@pytest.fixture
def calendar_stack(identity_service: MockIdentityService):
    repository = InMemoryCalendarRepository()
    membership_provider = SlackMembershipDirectoryProvider(
        slack_identity_service=identity_service,
    )
    audience_service = AudienceResolutionService(
        directory_provider=membership_provider,
        organization_channel_id="C_ORG_ANNOUNCE",
    )
    service = CalendarService(
        repository=repository,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )
    agent = CalendarAgent(
        service=service,
        default_timezone="Asia/Kolkata",
        identity_resolver=identity_service,
    )
    return {
        "repository": repository,
        "identity_service": identity_service,
        "audience_service": audience_service,
        "service": service,
        "agent": agent,
    }


# =============================================================================
# 1. RESOLUTION OF <@U...> MENTIONS AND RAW SLACK IDS
# =============================================================================


def test_resolve_slack_mention_resolves_display_name(calendar_stack):
    aud_svc = calendar_stack["audience_service"]
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="<@U0BU14F6CTD>",
    )
    assert aud.audience_type == CalendarAudienceType.INDIVIDUAL
    assert aud.audience_id == "U0BU14F6CTD"
    assert aud.display_name == "Hemant Kumar Sah"
    assert aud.resolved_recipients == ("U0BU14F6CTD",)


def test_resolve_raw_slack_id_resolves_display_name(calendar_stack):
    aud_svc = calendar_stack["audience_service"]
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U0BU14F6CTD",
    )
    assert aud.audience_type == CalendarAudienceType.INDIVIDUAL
    assert aud.audience_id == "U0BU14F6CTD"
    assert aud.display_name == "Hemant Kumar Sah"
    assert aud.resolved_recipients == ("U0BU14F6CTD",)


def test_untrusted_mention_label_does_not_override_authoritative_name(calendar_stack):
    aud_svc = calendar_stack["audience_service"]
    agent = calendar_stack["agent"]
    # U0BU14F6CTD is authoritative "Hemant Kumar Sah". The mention has a fake label.
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="<@U0BU14F6CTD|Fake CEO Name>",
    )
    assert aud.audience_id == "U0BU14F6CTD"
    assert aud.display_name == "Hemant Kumar Sah"
    assert "Fake CEO Name" not in aud.display_name

    # Verify agent resolution also prefers authoritative name
    resolved = agent._resolve_user_display_name("<@U0BU14F6CTD|Fake CEO Name>")
    assert resolved == "Hemant Kumar Sah"


def test_untrusted_mention_label_unresolved_user_safely_omitted(calendar_stack):
    aud_svc = calendar_stack["audience_service"]
    agent = calendar_stack["agent"]
    # U_UNKNOWN99 has no identity service record. Arbitrary label must not be trusted.
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="<@U_UNKNOWN99|Arbitrary Untrusted Label>",
    )
    assert aud.audience_id == "U_UNKNOWN99"
    # display_name must be empty, not the untrusted label and not the raw ID
    assert aud.display_name == ""
    assert "Arbitrary" not in aud.display_name

    # Agent must safely return None
    assert agent._resolve_user_display_name("<@U_UNKNOWN99|Arbitrary Untrusted Label>") is None


def test_trusted_mention_label_matching_identity_service(calendar_stack):
    aud_svc = calendar_stack["audience_service"]
    agent = calendar_stack["agent"]
    # When mention label matches the real user identity
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="<@U0123456789|Alice Wonderland>",
    )
    assert aud.audience_id == "U0123456789"
    assert aud.display_name == "Alice Wonderland"
    assert agent._resolve_user_display_name("<@U0123456789|Alice Wonderland>") == "Alice Wonderland"


def test_unverified_mention_label_cannot_override_or_produce_false_display_name(calendar_stack):
    """
    Proves that an unverified mention label cannot override the authoritative identity
    or produce a false display name, even if the label matches another real user in the
    workspace or if resolve_user returns an unverified user object with a mismatched ID.
    """
    agent = calendar_stack["agent"]

    # 1. Unknown canonical ID with a mention label spoofing another real user ("Alice Wonderland")
    # Alice exists in the workspace (U0123456789), but the mention's canonical ID is U_UNKNOWN99.
    # The mention label must NOT produce a false display name for U_UNKNOWN99.
    assert agent._resolve_user_display_name("<@U_UNKNOWN99|Alice Wonderland>") is None

    # 2. Known user U0BU14F6CTD ("Hemant Kumar Sah") with a mention label claiming to be "Alice Wonderland"
    # The mention label must NOT override the authoritative identity.
    assert agent._resolve_user_display_name("<@U0BU14F6CTD|Alice Wonderland>") == "Hemant Kumar Sah"

    # 3. When resolve_user returns a user object whose ID does not match cleaned_id,
    # the unverified user object must be rejected and return None.
    class MismatchedIdentityService(MockIdentityService):
        def get_display_name(self, user_id: str) -> str:
            return user_id  # Returns raw ID so fallback to resolve_user is attempted

        def resolve_user(self, name_or_id: str) -> dict | None:
            # Returns a user object with a mismatched ID
            return {"id": "U_DIFFERENT", "name": "Impostor Name", "real_name": "Impostor Name"}

    mismatched_agent = CalendarAgent(
        service=calendar_stack["service"],
        default_timezone="Asia/Kolkata",
        identity_resolver=MismatchedIdentityService(),
    )
    assert mismatched_agent._resolve_user_display_name("U_TARGET") is None
    assert mismatched_agent._resolve_user_display_name("<@U_TARGET|Spoofed Label>") is None


# =============================================================================
# 2. SAFE BEHAVIOR WHEN IDENTITY LOOKUP FAILS (NO RAW IDS LEAKED)
# =============================================================================


def test_resolve_user_provider_unresolved_returns_empty_name(calendar_stack):
    provider = calendar_stack["audience_service"].directory_provider
    res = provider.resolve_user("U_UNKNOWN99")
    assert res is not None
    assert res["id"] == "U_UNKNOWN99"
    # Must NOT return raw ID as name or real_name
    assert res["name"] == ""
    assert res["real_name"] == ""
    assert provider.get_user_id(res) == "U_UNKNOWN99"


def test_resolve_user_provider_untrusted_mention_label_rejected(calendar_stack):
    """
    Proves an untrusted mention label cannot supply a name when canonical-ID resolution fails.
    Even if the mention label matches another real user in the directory (e.g. 'Alice Wonderland'),
    the directory provider must not use that mention label to supply a name for U_UNKNOWN99.
    """
    provider = calendar_stack["audience_service"].directory_provider

    # 1. Arbitrary untrusted label on unresolved ID
    res1 = provider.resolve_user("<@U_UNKNOWN99|Arbitrary Untrusted Label>")
    assert res1 is not None
    assert res1["id"] == "U_UNKNOWN99"
    assert res1["name"] == ""
    assert res1["real_name"] == ""

    # 2. Mention label claiming another real user's name ('Alice Wonderland')
    res2 = provider.resolve_user("<@U_UNKNOWN99|Alice Wonderland>")
    assert res2 is not None
    assert res2["id"] == "U_UNKNOWN99"
    assert res2["name"] == ""
    assert res2["real_name"] == ""

    # 3. Mention label on failing ID
    res3 = provider.resolve_user("<@U_FAILING_ID|Fake Label>")
    assert res3 is not None
    assert res3["id"] == "U_FAILING_ID"
    assert res3["name"] == ""
    assert res3["real_name"] == ""


def test_resolve_user_provider_identity_failure_returns_empty_name(calendar_stack):
    provider = calendar_stack["audience_service"].directory_provider
    res = provider.resolve_user("U_FAILING_ID")
    assert res is not None
    assert res["id"] == "U_FAILING_ID"
    # Must NOT return raw ID as name or real_name
    assert res["name"] == ""
    assert res["real_name"] == ""
    assert provider.get_user_id(res) == "U_FAILING_ID"


def test_safe_behavior_when_identity_lookup_raises_exception(calendar_stack):
    aud_svc = calendar_stack["audience_service"]
    # U_FAILING_ID triggers a RuntimeError in MockIdentityService
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_FAILING_ID",
    )
    assert aud.audience_id == "U_FAILING_ID"
    # display_name must be empty, NEVER the raw ID
    assert aud.display_name == ""
    assert "U_FAILING_ID" not in aud.display_name


def test_safe_behavior_when_identity_returns_raw_id_as_display_name(calendar_stack):
    aud_svc = calendar_stack["audience_service"]
    # U_UNKNOWN_ID is not in names map, so get_display_name returns user_id
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_UNKNOWN_ID",
    )
    assert aud.audience_id == "U_UNKNOWN_ID"
    # Must NOT use the raw ID as display_name
    assert aud.display_name == ""


def test_resolve_user_fallback_never_called_when_get_display_name_returns_raw_id():
    """
    Regression test: When get_display_name() returns a raw ID (or unresolved value),
    SlackMembershipDirectoryProvider.resolve_user() must NEVER fall back to calling
    resolve_user() on the identity service, and the display name must remain empty,
    even if resolve_user() would have returned a misleading name.
    """
    class MisleadingIdentityService:
        def __init__(self):
            self.resolve_user_called = False

        def get_display_name(self, user_id: str) -> str:
            # Returns the raw ID, which is not an authoritative display name
            return user_id

        def resolve_user(self, name_or_id: str) -> dict | None:
            self.resolve_user_called = True
            return {
                "id": name_or_id,
                "name": "Misleading Impostor Name",
                "real_name": "Misleading Impostor Real Name",
            }

        def get_user_id(self, user: dict | None) -> str | None:
            return user.get("id") if user else None

    identity_svc = MisleadingIdentityService()
    provider = SlackMembershipDirectoryProvider(slack_identity_service=identity_svc)
    aud_svc = AudienceResolutionService(
        directory_provider=provider,
        organization_channel_id="C_MAIN",
    )

    # 1. Test directory provider directly with raw Slack ID
    res = provider.resolve_user("U_TARGET_99")
    assert res is not None
    assert res["id"] == "U_TARGET_99"
    assert res["name"] == ""
    assert res["real_name"] == ""
    assert not identity_svc.resolve_user_called, "resolve_user() must never be called as fallback for a canonical Slack ID"

    # 2. Test directory provider with Slack mention
    res_mention = provider.resolve_user("<@U_TARGET_99>")
    assert res_mention is not None
    assert res_mention["id"] == "U_TARGET_99"
    assert res_mention["name"] == ""
    assert not identity_svc.resolve_user_called, "resolve_user() must never be called for a mention"

    # 3. Test through AudienceResolutionService.resolve()
    aud = aud_svc.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET_99",
    )
    assert aud.audience_id == "U_TARGET_99"
    assert aud.display_name == ""
    assert not identity_svc.resolve_user_called, "resolve_user() must not be called during audience resolution"


# =============================================================================
# 3. RESOLVED NAMES IN SCHEDULING CONFIRMATIONS
# =============================================================================


def test_schedule_confirmation_uses_resolved_display_name(calendar_stack):
    agent = calendar_stack["agent"]
    msg = "schedule activity 'Quarterly 1:1' on 2026-11-20 14:00 for <@U0BU14F6CTD>"
    res = agent.handle_message(msg, user_id="U_CREATOR")

    assert res is not None
    assert "Successfully scheduled" in res
    assert "Quarterly 1:1" in res
    # Must contain the resolved display name
    assert "• *Audience:* individual (Hemant Kumar Sah)" in res
    # Must NOT expose raw ID in the audience line
    assert "individual (U0BU14F6CTD)" not in res


# =============================================================================
# 4. UNRESOLVED AUDIENCES WITHOUT RAW IDS IN RESPONSES
# =============================================================================


def test_schedule_confirmation_unresolved_audience_omits_raw_id(calendar_stack):
    agent = calendar_stack["agent"]
    # Schedule for a user whose display name cannot be resolved
    msg = "schedule activity 'Sync Session' on 2026-11-20 15:00 for U_FAILING_ID"
    res = agent.handle_message(msg, user_id="U_CREATOR")

    assert res is not None
    assert "Successfully scheduled" in res
    # Must safely format as individual without leaking raw ID
    assert "• *Audience:* individual" in res
    assert "individual (U_FAILING_ID)" not in res
    assert "U_FAILING_ID" not in res.split("• *Audience:*")[1].split("\n")[0]


# =============================================================================
# 5. PERSISTENCE AND BACKWARD COMPATIBILITY OF AUDIENCE_DISPLAY_NAME
# =============================================================================


def test_audience_display_name_persisted_in_metadata(calendar_stack):
    service = calendar_stack["service"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = service.create_entry(
        title="Performance Review",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U0BU14F6CTD",
    )

    # Check that metadata preserved audience_display_name
    assert "audience_display_name" in entry.metadata
    assert entry.metadata["audience_display_name"] == "Hemant Kumar Sah"

    # Reload from repository
    reloaded = service.get_entry(entry.entry_id)
    assert reloaded is not None
    assert reloaded.metadata.get("audience_display_name") == "Hemant Kumar Sah"


def test_backward_compatibility_with_legacy_entry_without_metadata(calendar_stack):
    agent = calendar_stack["agent"]
    service = calendar_stack["service"]
    repository = calendar_stack["repository"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    # Create a legacy entry directly without audience_display_name in metadata
    legacy_entry = CalendarEntry.create(
        title="Legacy Check-in",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        timezone_name="Asia/Kolkata",
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_id="U0BU14F6CTD",
        metadata={},  # No audience_display_name
    )
    saved = repository.save_entry(legacy_entry)

    # Agent should dynamically resolve the name via identity resolver
    res = agent.handle_message(
        f"who is the event {saved.entry_id} intended for",
        user_id="U_CREATOR",
    )
    assert res is not None
    assert "Hemant Kumar Sah" in res
    assert "U0BU14F6CTD" not in res


# =============================================================================
# 6. REMINDER STATUS WITH RESOLVED AND UNRESOLVED RECIPIENTS
# =============================================================================


def test_reminder_status_with_resolved_recipient(calendar_stack):
    agent = calendar_stack["agent"]
    service = calendar_stack["service"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = service.create_entry(
        title="Team Briefing",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U0BU14F6CTD",
    )

    status_res = agent.handle_message(
        f"reminder status for {entry.entry_id}",
        user_id="U_CREATOR",
    )
    assert status_res is not None
    assert "Reminder Delivery Status" in status_res
    # Must show resolved display name
    assert "Recipient: Hemant Kumar Sah" in status_res
    # Must NOT have raw ID in code backticks
    assert "`<@U0BU14F6CTD>`" not in status_res
    assert "<@U0BU14F6CTD>" not in status_res


def test_reminder_status_with_unresolved_recipient(calendar_stack):
    agent = calendar_stack["agent"]
    service = calendar_stack["service"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = service.create_entry(
        title="Confidential Briefing",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_FAILING_ID",
    )

    status_res = agent.handle_message(
        f"reminder status for {entry.entry_id}",
        user_id="U_CREATOR",
    )
    assert status_res is not None
    assert "Reminder Delivery Status" in status_res
    # Must use safe neutral label without leaking raw ID
    assert "Recipient (via dm)" in status_res
    assert "`<@U_FAILING_ID>`" not in status_res
    assert "U_FAILING_ID" not in status_res


# =============================================================================
# 7. INDIVIDUAL-AUDIENCE INSPECTION (_handle_who_is_for)
# =============================================================================


def test_who_is_for_with_resolved_individual(calendar_stack):
    agent = calendar_stack["agent"]
    service = calendar_stack["service"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = service.create_entry(
        title="Project Kickoff",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U0BU14F6CTD",
    )

    res = agent.handle_message(
        f"who is the event {entry.entry_id} intended for",
        user_id="U_CREATOR",
    )
    assert res is not None
    assert "intended for *Hemant Kumar Sah* (individual)" in res
    assert "U0BU14F6CTD" not in res


def test_who_is_for_with_unresolved_individual(calendar_stack):
    agent = calendar_stack["agent"]
    service = calendar_stack["service"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = service.create_entry(
        title="Unknown Contact Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_FAILING_ID",
    )

    res = agent.handle_message(
        f"who is the event {entry.entry_id} intended for",
        user_id="U_CREATOR",
    )
    assert res is not None
    assert "intended for an individual recipient." in res
    assert "U_FAILING_ID" not in res


def test_format_audience_team_without_display_name_omits_internal_id(calendar_stack):
    """
    Response path 1: _format_audience() with a team entry lacking audience_display_name
    must return 'team' without exposing internal-looking audience_id.
    """
    agent = calendar_stack["agent"]
    repository = calendar_stack["repository"]
    start = datetime.now(timezone.utc) + timedelta(days=2)

    entry = CalendarEntry.create(
        title="Team Standup",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.TEAM,
        audience_id="T_INTERNAL_TEAM_99",
        metadata={},  # No audience_display_name
    )
    repository.save_entry(entry)

    # 1. Direct _format_audience check
    formatted = agent._format_audience(entry)
    assert formatted == "team"
    assert "T_INTERNAL_TEAM_99" not in formatted

    # 2. View / list output check
    view_res = agent.handle_message("view calendar", user_id="U_CREATOR")
    assert view_res is not None
    assert "Audience: team" in view_res
    assert "T_INTERNAL_TEAM_99" not in view_res


def test_format_audience_team_with_display_name_uses_display_name(calendar_stack):
    """
    Response path 1: _format_audience() with a team entry having audience_display_name
    must return 'team (<display_name>)'.
    """
    agent = calendar_stack["agent"]
    repository = calendar_stack["repository"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = CalendarEntry.create(
        title="Platform Planning",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.TEAM,
        audience_id="T_INTERNAL_TEAM_99",
        metadata={"audience_display_name": "Platform Engineering"},
    )
    repository.save_entry(entry)

    formatted = agent._format_audience(entry)
    assert formatted == "team (Platform Engineering)"
    assert "T_INTERNAL_TEAM_99" not in formatted


def test_who_is_for_team_without_display_name_omits_internal_id(calendar_stack):
    """
    Response path 2: _handle_who_is_for() with a team entry lacking audience_display_name
    must say the entry is intended for 'a team' without including entry.audience_id.
    """
    agent = calendar_stack["agent"]
    repository = calendar_stack["repository"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = CalendarEntry.create(
        title="Architecture Review",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.TEAM,
        audience_id="T_INTERNAL_TEAM_99",
        metadata={},  # No audience_display_name
    )
    repository.save_entry(entry)

    res = agent.handle_message(
        f"who is the event {entry.entry_id} intended for",
        user_id="U_CREATOR",
    )
    assert res is not None
    assert f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for a team." in res
    assert "T_INTERNAL_TEAM_99" not in res


def test_who_is_for_team_with_display_name_uses_display_name(calendar_stack):
    """
    Response path 2: _handle_who_is_for() with a team entry having audience_display_name
    must include the display name without exposing entry.audience_id.
    """
    agent = calendar_stack["agent"]
    repository = calendar_stack["repository"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = CalendarEntry.create(
        title="Security Audit Review",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.TEAM,
        audience_id="T_INTERNAL_TEAM_99",
        metadata={"audience_display_name": "Security Team"},
    )
    repository.save_entry(entry)

    res = agent.handle_message(
        f"who is the event {entry.entry_id} intended for",
        user_id="U_CREATOR",
    )
    assert res is not None
    assert f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for the *Security Team* team." in res
    assert "T_INTERNAL_TEAM_99" not in res


# =============================================================================
# 8. PRESERVATION OF INTERNAL IDS FOR TECHNICAL OPERATIONS
# =============================================================================


def test_internal_ids_preserved_for_db_and_auth(calendar_stack):
    service = calendar_stack["service"]
    repository = calendar_stack["repository"]
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = service.create_entry(
        title="Technical Operation Check",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U0BU14F6CTD",
    )

    # 1. Entry audience_id must remain the internal ID
    assert entry.audience_id == "U0BU14F6CTD"
    assert entry.creator_id == "U_CREATOR"

    # 2. Persisted entity in repository has correct internal IDs
    persisted = repository.find_entry(entry.entry_id)
    assert persisted is not None
    assert persisted.audience_id == "U0BU14F6CTD"
    assert persisted.creator_id == "U_CREATOR"

    # 3. Scheduled deliveries maintain internal recipient ID
    deliveries = repository.find_deliveries_for_entry(entry.entry_id)
    assert len(deliveries) == 1
    assert deliveries[0].recipient_id == "U0BU14F6CTD"

    # 4. Visibility check works with internal user ID
    assert entry.is_visible_to("U0BU14F6CTD") is True
    assert entry.is_visible_to("U_CREATOR") is True
    assert entry.is_visible_to("U_STRANGER") is False

    # 5. List entries visible to user
    visible = service.list_entries_visible_to("U0BU14F6CTD")
    assert any(e.entry_id == entry.entry_id for e in visible)

    visible_stranger = service.list_entries_visible_to("U_STRANGER")
    assert not any(e.entry_id == entry.entry_id for e in visible_stranger)
