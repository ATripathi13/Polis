"""
Unit tests for CalendarAgent specialist interaction and POLIS orchestration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from domain.calendar import (
    CalendarAudienceType,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderPolicy,
    InMemoryCalendarRepository,
)
from domain.reasoning.value_objects import Question
from application.calendar import (
    AudienceResolutionService,
    CalendarAgent,
    CalendarService,
    SlackMembershipDirectoryProvider,
)
from application.cognitive import SimpleCognitiveEngine


class MockSlackIdentityService:
    def resolve_user(self, name: str) -> dict | None:
        clean = name.strip()
        if clean.startswith("<@") and clean.endswith(">"):
            uid = clean[2:-1].split("|")[0]
            return {"id": uid, "name": uid}
        return {"id": f"U_{clean.upper()}", "name": clean}

    def get_user_id(self, user: dict | None) -> str | None:
        return user.get("id") if user else None

    def get_workspace_users(self) -> list[dict]:
        return [{"id": "U_USER1"}, {"id": "U_USER2"}]


@pytest.fixture
def repo() -> InMemoryCalendarRepository:
    return InMemoryCalendarRepository()


@pytest.fixture
def calendar_agent(repo) -> CalendarAgent:
    provider = SlackMembershipDirectoryProvider(
        slack_identity_service=MockSlackIdentityService(),
        team_roster_provider=lambda team: ["U_DEV1", "U_DEV2"],
    )
    audience_service = AudienceResolutionService(
        directory_provider=provider,
        organization_channel_id="C_MAIN",
    )
    service = CalendarService(
        repository=repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )
    return CalendarAgent(
        service=service,
        default_timezone="Asia/Kolkata",
    )


def test_handle_schedule_activity_command(calendar_agent):
    msg = "schedule activity 'Sprint Planning' on 2026-11-20 10:00 for the team dev"
    res = calendar_agent.handle_message(msg, user_id="U_CREATOR")

    assert res is not None
    assert "Successfully scheduled" in res
    assert "Sprint Planning" in res
    assert "15 hours before start" in res

    # Verify persisted in repository
    entries = calendar_agent.service.list_entries()
    assert len(entries) == 1
    assert entries[0].title == "Sprint Planning"
    assert entries[0].entry_type == CalendarEntryType.ACTIVITY


def test_handle_schedule_holiday_command(calendar_agent):
    msg = "schedule a holiday 'New Year' on 2027-01-01 09:00 for the organization"
    res = calendar_agent.handle_message(msg, user_id="U_HR")

    assert res is not None
    assert "Successfully scheduled" in res
    assert "New Year" in res
    assert "organization" in res


def test_handle_missing_date_asks_for_clarification(calendar_agent):
    msg = "schedule activity 'Q4 Review' for organization"
    res = calendar_agent.handle_message(msg, user_id="U_CREATOR")

    assert "When is this scheduled to take place?" in res
    # Must NOT have created an entry without a date
    assert len(calendar_agent.service.list_entries()) == 0


def test_handle_missing_title_asks_for_clarification(calendar_agent):
    msg = "schedule an activity on 2026-11-20 10:00 for organization"
    res = calendar_agent.handle_message(msg, user_id="U_CREATOR")

    assert "What is the title of the entry?" in res
    assert len(calendar_agent.service.list_entries()) == 0


def test_handle_list_and_view_calendar(calendar_agent):
    # Schedule an entry first
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=2)

    calendar_agent.service.create_entry(
        title="Architecture Workshop",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=future.astimezone(tz),
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_identifier="organization",
    )

    list_res = calendar_agent.handle_message("what is on the calendar?", user_id="U_USER1")
    assert list_res is not None
    assert "Architecture Workshop" in list_res


def test_handle_cancel_event(calendar_agent):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = calendar_agent.service.create_entry(
        title="Sync Meeting",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_CREATOR",
    )

    cancel_res = calendar_agent.handle_message(f"cancel event {entry.entry_id}", user_id="U_CREATOR")
    assert cancel_res is not None
    assert "Successfully cancelled" in cancel_res

    updated = calendar_agent.service.get_entry(entry.entry_id)
    assert updated.status == CalendarEntryStatus.CANCELLED


def test_handle_reminder_status_query(calendar_agent):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = calendar_agent.service.create_entry(
        title="Keynote",
        entry_type=CalendarEntryType.ANNOUNCEMENT,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_VIP",
    )

    status_res = calendar_agent.handle_message(f"reminder status for {entry.entry_id}", user_id="U_CREATOR")
    assert status_res is not None
    assert "Reminder Delivery Status" in status_res
    assert "PENDING" in status_res


def test_handle_who_is_for_query_hides_team_entry_from_unverified_member(
    calendar_agent,
):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 12, 1, 10, 0, tzinfo=tz)

    entry = calendar_agent.service.create_entry(
        title="Team Offsite",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.TEAM,
        audience_identifier="dev",
    )

    res = calendar_agent.handle_message(
        f"who is the event {entry.entry_id} intended for",
        user_id="U_USER",
    )

    assert res is not None
    assert "Could not find a calendar entry" in res
    assert "Team Offsite" not in res
    assert "U_CREATOR" not in res


def test_non_calendar_message_returns_none(calendar_agent):
    msg = "How do I configure the MinIO bucket?"
    res = calendar_agent.handle_message(msg, user_id="U_USER")
    assert res is None


def test_cognitive_engine_evidence_integration(calendar_agent):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime.now(timezone.utc) + timedelta(days=3)

    calendar_agent.service.create_entry(
        title="Company Hackathon",
        description="Annual 48-hour hackathon",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start.astimezone(tz),
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_identifier="organization",
    )

    # Ask evidence for calendar question
    q = Question(text="What is on the upcoming calendar?")
    evidence = calendar_agent.retrieve_evidence(q)
    assert len(evidence) >= 1
    assert any("Company Hackathon" in ev for ev in evidence)

    # Ask evidence for unrelated question
    unrelated_q = Question(text="What is the database password?")
    unrelated_ev = calendar_agent.retrieve_evidence(unrelated_q)
    assert len(unrelated_ev) == 0


def test_cognitive_engine_wiring(calendar_agent):
    class FakePipeline:
        pass

    class FakeQA:
        def answer(self, q):
            return "fallback"

    engine = SimpleCognitiveEngine(
        pipeline=FakePipeline(),
        question_answering=FakeQA(),
        calendar_agent=calendar_agent,
    )

    assert engine.calendar_agent is calendar_agent
    res = engine.ask_calendar("what are upcoming events?")
    assert res is not None
    assert "evidence" in res


def test_cognitive_evidence_excludes_private_entries_without_requester(
    calendar_agent,
):
    start = datetime.now(timezone.utc) + timedelta(days=3)

    calendar_agent.service.create_entry(
        title="Private One-to-One",
        description="Confidential discussion",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET",
    )

    evidence = calendar_agent.retrieve_evidence(
        Question(text="What is on the upcoming calendar?")
    )

    assert not any("Private One-to-One" in item for item in evidence)
    assert not any("Confidential discussion" in item for item in evidence)


def test_cognitive_evidence_does_not_expose_reminder_delivery_details(
    calendar_agent,
):
    start = datetime.now(timezone.utc) + timedelta(days=3)

    calendar_agent.service.create_entry(
        title="Company Hackathon",
        description="Annual event",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_identifier="organization",
    )

    evidence = calendar_agent.retrieve_evidence(
        Question(
            text="What is on the upcoming calendar?",
            context=__import__(
                "domain.reasoning.value_objects",
                fromlist=["ConversationContext"],
            ).ConversationContext(
                user_id="U_VIEWER",
                channel_id="C_MAIN",
                thread_ts="123.456",
            ),
        )
    )

    combined = "\n".join(evidence)

    assert "Company Hackathon" in combined
    assert "Reminders:" not in combined
    assert "U_CREATOR:" not in combined

def test_reminder_status_hides_delivery_details_from_non_creator(
    calendar_agent,
):
    start = datetime.now(timezone.utc) + timedelta(days=3)

    entry = calendar_agent.service.create_entry(
        title="Confidential Announcement",
        entry_type=CalendarEntryType.ANNOUNCEMENT,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_identifier="organization",
    )

    response = calendar_agent.handle_message(
        f"reminder status for {entry.entry_id}",
        user_id="U_VIEWER",
    )

    assert response is not None
    assert "not authorized" in response.lower()
    assert "U_VIP" not in response
    assert "Recipient:" not in response
    assert "Attempts:" not in response

def test_cognitive_evidence_includes_private_entry_for_authorized_requester(
    calendar_agent,
):
    start = datetime.now(timezone.utc) + timedelta(days=3)

    calendar_agent.service.create_entry(
        title="My Private One-to-One",
        description="Personal discussion",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="TARGET",
    )

    from domain.reasoning.value_objects.conversation_context import ConversationContext

    evidence = calendar_agent.retrieve_evidence(
        Question(
            text="What is on the upcoming calendar?",
            context=ConversationContext(
                user_id="U_TARGET",
                channel_id="C_MAIN",
                thread_ts="123.456",
            ),
        )
    )

    assert any("My Private One-to-One" in item for item in evidence)
    assert any("Personal discussion" in item for item in evidence)

def test_handle_structured_slack_holiday_request(calendar_agent):
    msg = (
        "POLIS, add a company calendar entry:\n"
        "- Title: Guru Nanak Jayanti — Fixed Paid Holiday\n"
        "- Date: 24 November 2026\n"
        "- Time: 9:00 AM IST\n"
        "- Type: Holiday\n"
        "- Audience: Whole Organization\n"
        "- Description: Fixed paid holiday under company holiday policy.\n"
        "Please confirm the saved date, timezone, audience, and reminder scheduling status."
    )

    response = calendar_agent.handle_message(msg, user_id="U_HR", channel_id="C_MAIN")

    assert response is not None
    assert "Successfully scheduled" in response

    entries = calendar_agent.service.list_entries()
    assert len(entries) == 1

    entry = entries[0]
    assert entry.title == "Guru Nanak Jayanti — Fixed Paid Holiday"
    assert entry.entry_type == CalendarEntryType.HOLIDAY
    assert entry.start_time.astimezone(ZoneInfo("Asia/Kolkata")) == datetime(
        2026, 11, 24, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")
    )
    assert entry.timezone == "Asia/Kolkata"
    assert entry.audience_type == CalendarAudienceType.ORGANIZATION
    assert entry.audience_id == "organization"
    assert entry.description == "Fixed paid holiday under company holiday policy."

    deliveries = calendar_agent.service._repository.find_deliveries_for_entry(
        entry.entry_id
    )
    assert len(deliveries) >= 1
