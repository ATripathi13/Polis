"""
Unit tests for POLIS Phase 3.3 Stage B2: Calendar Structured Execution.

Covers:
1. Structured calendar creation.
2. Structured calendar update.
3. Structured calendar cancellation.
4. Missing title or start time.
5. Missing entry ID for update/cancellation.
6. Invalid date/time/timezone.
7. Duration-based end-time derivation.
8. Audience type and identifier validation.
9. Creator-only update authorization.
10. Creator-only cancellation authorization.
11. Reminder scheduling remains intact after creation.
12. Rescheduling preserves existing pending-reminder cancellation behavior.
13. handle_message() fallback for supported natural-language requests.
14. handle_message() returning None does not cause silent fall-through.
15. Calendar service unavailable.
16. Service exceptions produce truthful failure responses.
17. Successful operations clear pending state.
18. Failed operations preserve pending state.
19. Task dispatch from B1 remains unaffected.
20. Unrelated intents are not intercepted by calendar dispatch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
import pytest

from domain.calendar import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderPolicy,
    InMemoryCalendarRepository,
)
from domain.calendar.exceptions import (
    CalendarDomainError,
    InvalidCalendarEntryError,
    InvalidTimeRangeError,
)
from domain.reasoning.value_objects import (
    ActionType,
    Answer,
    CognitivePlan,
    ConversationContext,
    ExecutionStep,
    ExtractedEntities,
    IntentCategory,
    Question,
    TargetAgent,
)
from application.calendar import (
    AudienceResolutionService,
    CalendarAgent,
    CalendarService,
)
from application.cognitive import SimpleCognitiveEngine


class MockDirectoryProvider:
    def resolve_user(self, identifier_or_name: str) -> dict | None:
        clean = identifier_or_name.strip()
        if clean.startswith("<@") and clean.endswith(">"):
            uid = clean[2:-1].split("|")[0]
            return {"id": uid, "name": uid, "real_name": uid}
        if clean.upper() in ("U_ALICE", "U_BOB", "U_CREATOR", "U_OTHER"):
            return {"id": clean.upper(), "name": clean, "real_name": clean}
        if clean.lower() == "alice":
            return {"id": "U_ALICE", "name": "alice", "real_name": "Alice"}
        if clean.lower() == "bob":
            return {"id": "U_BOB", "name": "bob", "real_name": "Bob"}
        return None

    def get_user_id(self, user: dict | None) -> str | None:
        return user.get("id") if user else None

    def get_team_members(self, team_id_or_name: str) -> list[str]:
        if team_id_or_name.lower() in ("dev", "engineering"):
            return ["U_ALICE", "U_BOB"]
        return []

    def get_all_workspace_user_ids(self) -> list[str]:
        return ["U_ALICE", "U_BOB", "U_CREATOR", "U_OTHER"]


@pytest.fixture
def calendar_repo() -> InMemoryCalendarRepository:
    return InMemoryCalendarRepository()


@pytest.fixture
def audience_service() -> AudienceResolutionService:
    return AudienceResolutionService(
        directory_provider=MockDirectoryProvider(),
        organization_channel_id="C_MAIN",
    )


@pytest.fixture
def calendar_service(calendar_repo, audience_service) -> CalendarService:
    return CalendarService(
        repository=calendar_repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )


@pytest.fixture
def calendar_agent(calendar_service) -> CalendarAgent:
    return CalendarAgent(
        service=calendar_service,
        default_timezone="Asia/Kolkata",
    )


def _make_calendar_plan(
    action: str = "create_event",
    action_type: ActionType = ActionType.CREATE,
    parameters: dict | None = None,
    entities: ExtractedEntities | None = None,
    intent: IntentCategory = IntentCategory.CALENDAR_ACTION,
) -> CognitivePlan:
    return CognitivePlan(
        request_id="plan_test_cal",
        original_message="Calendar action request",
        intent=intent,
        intent_confidence=1.0,
        requested_outcome="Execute calendar operation",
        entities=entities or ExtractedEntities(),
        required_agents=[TargetAgent.CALENDAR_AGENT],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.CALENDAR_AGENT,
                action=action,
                action_type=action_type,
                parameters=dict(parameters or {}),
            )
        ],
        missing_information=[],
        requires_clarification=False,
        clarification_prompt=None,
        action_required=True,
        risk_level="low",
    )


# =========================================================================
# 1. Structured calendar creation
# =========================================================================

def test_structured_calendar_creation(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Architecture Sync",
            "start_time": "2026-11-20T10:00:00+05:30",
            "audience_type": "individual",
            "audience_identifier": "U_BOB",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    q = Question(text="Schedule Architecture Sync with Bob", context=ctx)
    ans = engine.ask(q)

    assert "Successfully scheduled" in ans.text
    assert "Architecture Sync" in ans.text
    assert ans.clear_pending is True

    entries = calendar_repo.list_entries()
    assert len(entries) == 1
    assert entries[0].title == "Architecture Sync"
    assert entries[0].creator_id == "U_ALICE"
    assert entries[0].audience_type == CalendarAudienceType.INDIVIDUAL
    assert entries[0].audience_id == "U_BOB"


# =========================================================================
# 2. Structured calendar update
# =========================================================================

def test_structured_calendar_update(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    tz = ZoneInfo("Asia/Kolkata")
    initial_start = datetime(2026, 11, 20, 10, 0, tzinfo=tz)
    created = calendar_agent.service.create_entry(
        title="Architecture Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=initial_start,
        timezone_name="Asia/Kolkata",
        audience_type=CalendarAudienceType.TEAM,
        audience_identifier="dev",
    )

    plan = _make_calendar_plan(
        action="update_event",
        action_type=ActionType.UPDATE,
        parameters={
            "entry_id": created.entry_id,
            "title": "Architecture Sync Rescheduled",
            "start_time": "2026-11-22T14:00:00+05:30",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    q = Question(text="Reschedule Architecture Sync", context=ctx)
    ans = engine.ask(q)

    assert "Successfully rescheduled" in ans.text
    assert "Architecture Sync Rescheduled" in ans.text
    assert "*Version:* 2" in ans.text
    assert ans.clear_pending is True

    updated_entry = calendar_repo.find_entry(created.entry_id)
    assert updated_entry is not None
    assert updated_entry.title == "Architecture Sync Rescheduled"
    assert updated_entry.version == 2


# =========================================================================
# 3. Structured calendar cancellation
# =========================================================================

def test_structured_calendar_cancellation(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    tz = ZoneInfo("Asia/Kolkata")
    initial_start = datetime(2026, 11, 20, 10, 0, tzinfo=tz)
    created = calendar_agent.service.create_entry(
        title="Architecture Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=initial_start,
        timezone_name="Asia/Kolkata",
        audience_type=CalendarAudienceType.TEAM,
        audience_identifier="dev",
    )

    plan = _make_calendar_plan(
        action="cancel_event",
        action_type=ActionType.CANCEL,
        parameters={
            "entry_id": created.entry_id,
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    q = Question(text="Cancel Architecture Sync", context=ctx)
    ans = engine.ask(q)

    assert "Successfully cancelled" in ans.text
    assert created.title in ans.text
    assert ans.clear_pending is True

    cancelled_entry = calendar_repo.find_entry(created.entry_id)
    assert cancelled_entry is not None
    assert cancelled_entry.status == CalendarEntryStatus.CANCELLED


# =========================================================================
# 4. Missing title or start time
# =========================================================================

def test_missing_title_or_start_time(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Missing title
    plan_no_title = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "start_time": "2026-11-20T10:00:00+05:30",
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan_no_title

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans1 = engine.ask(Question(text="Schedule an event", context=ctx))

    assert ans1.clear_pending is False
    assert len(calendar_repo.list_entries()) == 0

    # Missing start time
    plan_no_time = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Meeting Without Time",
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan_no_time
    ans2 = engine.ask(Question(text="Schedule Meeting Without Time", context=ctx))

    assert ans2.clear_pending is False
    assert len(calendar_repo.list_entries()) == 0


# =========================================================================
# 5. Missing entry ID for update/cancellation
# =========================================================================

def test_missing_entry_id_for_update_cancellation(calendar_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Update without entry ID
    plan_update = _make_calendar_plan(
        action="update_event",
        action_type=ActionType.UPDATE,
        parameters={
            "start_time": "2026-11-22T14:00:00+05:30",
        },
    )
    planner.plan.return_value = plan_update

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans_up = engine.ask(Question(text="Update meeting time", context=ctx))

    assert "Cannot update calendar entry: entry ID is required" in ans_up.text
    assert ans_up.clear_pending is False

    # Cancel without entry ID
    plan_cancel = _make_calendar_plan(
        action="cancel_event",
        action_type=ActionType.CANCEL,
        parameters={},
    )
    planner.plan.return_value = plan_cancel

    ans_can = engine.ask(Question(text="Cancel meeting", context=ctx))

    assert "Cannot cancel calendar entry: entry ID is required" in ans_can.text
    assert ans_can.clear_pending is False


# =========================================================================
# 6. Invalid date/time/timezone
# =========================================================================

def test_invalid_date_time_timezone(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Invalid timezone
    plan_invalid_tz = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Bad TZ Event",
            "start_time": "2026-11-20T10:00:00",
            "timezone_name": "Mars/Olympus",
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan_invalid_tz

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Schedule with bad TZ", context=ctx))

    assert ans.clear_pending is False
    assert "Invalid timezone" in ans.text
    assert len(calendar_repo.list_entries()) == 0

    # End time before start time
    plan_reversed_time = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Backwards Event",
            "start_time": "2026-11-20T10:00:00+05:30",
            "end_time": "2026-11-20T09:00:00+05:30",
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan_reversed_time
    ans2 = engine.ask(Question(text="Schedule backwards event", context=ctx))

    assert ans2.clear_pending is False
    assert "End time cannot precede start time" in ans2.text
    assert len(calendar_repo.list_entries()) == 0


# =========================================================================
# 7. Duration-based end-time derivation
# =========================================================================

def test_duration_based_end_time_derivation(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Sprint Review",
            "start_time": "2026-11-20T10:00:00+05:30",
            "duration_minutes": 45,
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Schedule 45 min Sprint Review", context=ctx))

    assert ans.clear_pending is True
    entries = calendar_repo.list_entries()
    assert len(entries) == 1
    assert entries[0].end_time == entries[0].start_time + timedelta(minutes=45)

    # Invalid non-positive duration
    plan_bad_dur = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Bad Duration Event",
            "start_time": "2026-11-20T10:00:00+05:30",
            "duration_minutes": -15,
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan_bad_dur
    ans_bad = engine.ask(Question(text="Schedule bad duration", context=ctx))

    assert ans_bad.clear_pending is False
    assert "duration_minutes must be a positive integer" in ans_bad.text


# =========================================================================
# 8. Audience type and identifier validation
# =========================================================================

def test_audience_type_and_identifier_validation(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Unknown individual
    plan_unknown_user = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "1-on-1 with Ghost",
            "start_time": "2026-11-20T10:00:00+05:30",
            "audience_type": "individual",
            "audience_identifier": "U_NONEXISTENT",
        },
    )
    planner.plan.return_value = plan_unknown_user

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Schedule with ghost", context=ctx))

    assert ans.clear_pending is False
    assert "Cannot resolve individual recipient" in ans.text
    assert len(calendar_repo.list_entries()) == 0

    # Unsupported audience type
    plan_bad_type = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Cosmic Announcement",
            "start_time": "2026-11-20T10:00:00+05:30",
            "audience_type": "galaxy",
            "audience_identifier": "all",
        },
    )
    planner.plan.return_value = plan_bad_type
    ans_bad_type = engine.ask(Question(text="Schedule for galaxy", context=ctx))

    assert ans_bad_type.clear_pending is False
    assert "Unsupported audience type" in ans_bad_type.text


# =========================================================================
# 9. Creator-only update authorization
# =========================================================================

def test_creator_only_update_authorization(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    tz = ZoneInfo("Asia/Kolkata")
    created = calendar_agent.service.create_entry(
        title="Alice Exclusive Event",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=datetime(2026, 11, 20, 10, 0, tzinfo=tz),
        timezone_name="Asia/Kolkata",
        audience_type=CalendarAudienceType.TEAM,
        audience_identifier="dev",
    )

    plan = _make_calendar_plan(
        action="update_event",
        action_type=ActionType.UPDATE,
        parameters={
            "entry_id": created.entry_id,
            "title": "Bob Hijack Attempt",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    # Bob attempts to update Alice's event
    ctx_bob = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_BOB")
    ans = engine.ask(Question(text="Update Alice's event", context=ctx_bob))

    assert "Only the creator can modify or cancel it" in ans.text
    assert ans.clear_pending is False

    entry_in_repo = calendar_repo.find_entry(created.entry_id)
    assert entry_in_repo.title == "Alice Exclusive Event"


# =========================================================================
# 10. Creator-only cancellation authorization
# =========================================================================

def test_creator_only_cancellation_authorization(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    tz = ZoneInfo("Asia/Kolkata")
    created = calendar_agent.service.create_entry(
        title="Alice Event To Keep",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=datetime(2026, 11, 20, 10, 0, tzinfo=tz),
        timezone_name="Asia/Kolkata",
        audience_type=CalendarAudienceType.TEAM,
        audience_identifier="dev",
    )

    plan = _make_calendar_plan(
        action="cancel_event",
        action_type=ActionType.CANCEL,
        parameters={
            "entry_id": created.entry_id,
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    # Bob attempts to cancel Alice's event
    ctx_bob = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_BOB")
    ans = engine.ask(Question(text="Cancel Alice's event", context=ctx_bob))

    assert "Only the creator can modify or cancel it" in ans.text
    assert ans.clear_pending is False

    entry_in_repo = calendar_repo.find_entry(created.entry_id)
    assert entry_in_repo.status == CalendarEntryStatus.SCHEDULED


# =========================================================================
# 11. Reminder scheduling remains intact after creation
# =========================================================================

def test_reminder_scheduling_remains_intact_after_creation(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    start_iso = "2026-11-20T10:00:00+05:30"
    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Mandatory Reminder Event",
            "start_time": start_iso,
            "audience_type": "individual",
            "audience_identifier": "U_BOB",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Schedule with reminder", context=ctx))

    assert ans.clear_pending is True
    entries = calendar_repo.list_entries()
    assert len(entries) == 1
    entry = entries[0]

    deliveries = calendar_repo.find_deliveries_for_entry(entry.entry_id)
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.status == CalendarDeliveryStatus.PENDING
    assert delivery.recipient_id == "U_BOB"
    # Exactly 15 hours before start
    expected_due = entry.start_time - timedelta(hours=15)
    assert delivery.due_at == expected_due


# =========================================================================
# 12. Rescheduling preserves existing pending-reminder cancellation behavior
# =========================================================================

def test_rescheduling_preserves_existing_pending_reminder_cancellation(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    tz = ZoneInfo("Asia/Kolkata")
    created = calendar_agent.service.create_entry(
        title="Sprint Planning",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=datetime(2026, 11, 20, 10, 0, tzinfo=tz),
        timezone_name="Asia/Kolkata",
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_BOB",
    )

    initial_deliveries = calendar_repo.find_deliveries_for_entry(created.entry_id)
    assert len(initial_deliveries) == 1
    assert initial_deliveries[0].status == CalendarDeliveryStatus.PENDING

    # Reschedule
    new_start_iso = "2026-11-25T14:00:00+05:30"
    plan = _make_calendar_plan(
        action="update_event",
        action_type=ActionType.UPDATE,
        parameters={
            "entry_id": created.entry_id,
            "start_time": new_start_iso,
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Reschedule Sprint Planning", context=ctx))

    assert ans.clear_pending is True

    # Initial delivery must now be CANCELLED
    assert initial_deliveries[0].status == CalendarDeliveryStatus.CANCELLED

    # New delivery scheduled for new start time - 15h
    all_deliveries = calendar_repo.find_deliveries_for_entry(created.entry_id)
    pending_deliveries = [d for d in all_deliveries if d.status == CalendarDeliveryStatus.PENDING]
    assert len(pending_deliveries) == 1
    updated_entry = calendar_repo.find_entry(created.entry_id)
    assert pending_deliveries[0].due_at == updated_entry.start_time - timedelta(hours=15)


# =========================================================================
# 13. handle_message() fallback for supported natural-language requests
# =========================================================================

def test_handle_message_fallback_for_supported_natural_language(calendar_agent, calendar_repo):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Plan has empty structured parameters -> insufficient -> triggers handle_message fallback
    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    q = Question(
        text="schedule activity 'Standup' on 2026-11-20 10:00 for the dev team",
        context=ctx,
    )
    ans = engine.ask(q)

    assert "Successfully scheduled" in ans.text
    assert "Standup" in ans.text
    assert ans.clear_pending is True

    entries = calendar_repo.list_entries()
    assert len(entries) == 1
    assert entries[0].title == "Standup"


# =========================================================================
# 14. handle_message() returning None does not cause silent fall-through
# =========================================================================

def test_handle_message_returning_none_does_not_cause_silent_fall_through(calendar_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    qa.retrieve_evidence = MagicMock()
    qa.answer_from_evidence = MagicMock()
    planner = MagicMock()

    # Plan with insufficient parameters
    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    # Natural language query that handle_message() cannot parse
    q = Question(
        text="Can we discuss our company history and founders?",
        context=ctx,
    )
    ans = engine.ask(q)

    # Must NOT silently fall through to general QA evidence retrieval / synthesis
    qa.retrieve_evidence.assert_not_called()
    qa.answer_from_evidence.assert_not_called()

    # Must return explicit clarification/failure response
    assert "I understood you wanted to perform a calendar action" in ans.text
    assert ans.clear_pending is False


# =========================================================================
# 15. Calendar service unavailable
# =========================================================================

def test_calendar_service_unavailable():
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={"title": "Sync"},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=None,  # Unavailable
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Schedule meeting", context=ctx))

    assert "Calendar service is currently unavailable" in ans.text
    assert ans.clear_pending is False


# =========================================================================
# 16. Service exceptions produce truthful failure responses
# =========================================================================

def test_service_exceptions_produce_truthful_failure_responses(calendar_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Broken Event",
            "start_time": "2026-11-20T10:00:00+05:30",
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan

    # Simulate database / domain error in service
    calendar_agent.execute_structured = MagicMock(
        side_effect=CalendarDomainError("Persistence layer failure")
    )

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Schedule broken event", context=ctx))

    assert "Calendar action failed: Persistence layer failure" in ans.text
    assert ans.clear_pending is False


# =========================================================================
# 17. Successful operations clear pending state
# =========================================================================

def test_successful_operations_clear_pending_state(calendar_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    plan = _make_calendar_plan(
        action="create_event",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Clear Pending Event",
            "start_time": "2026-11-20T10:00:00+05:30",
            "audience_type": "team",
            "audience_identifier": "dev",
        },
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="100.1",
        user_id="U_ALICE",
        pending_operation={"operation_id": "op_test"},
    )
    ans = engine.ask(Question(text="Schedule event", context=ctx))

    assert ans.clear_pending is True


# =========================================================================
# 18. Failed operations preserve pending state
# =========================================================================

def test_failed_operations_preserve_pending_state(calendar_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    planner = MagicMock()

    # Plan fails due to missing entry ID
    plan = _make_calendar_plan(
        action="cancel_event",
        action_type=ActionType.CANCEL,
        parameters={},
    )
    planner.plan.return_value = plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(
        channel_id="C_MAIN",
        thread_ts="100.1",
        user_id="U_ALICE",
        pending_operation={"operation_id": "op_test"},
    )
    ans = engine.ask(Question(text="Cancel", context=ctx))

    assert ans.clear_pending is False


# =========================================================================
# 19. Task dispatch from B1 remains unaffected
# =========================================================================

def test_task_dispatch_from_b1_remains_unaffected(calendar_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    operations_agent = MagicMock()
    planner = MagicMock()

    mock_op_result = MagicMock()
    mock_op_result.operation = "created"
    mock_op_result.item = MagicMock(summary="Deploy to Production")
    mock_op_result.item.identifier.graph_id = "task_999"
    operations_agent.process_event.return_value = mock_op_result

    task_plan = CognitivePlan(
        request_id="plan_task_b1",
        original_message="Create a task",
        intent=IntentCategory.TASK_ACTION,
        intent_confidence=1.0,
        requested_outcome="Create task",
        entities=ExtractedEntities(task_summary="Deploy to Production"),
        required_agents=[TargetAgent.OPERATIONS_AGENT],
        execution_steps=[
            ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.OPERATIONS_AGENT,
                action="create_task",
                action_type=ActionType.CREATE,
                parameters={"summary": "Deploy to Production"},
            )
        ],
        missing_information=[],
        requires_clarification=False,
        clarification_prompt=None,
        action_required=True,
        risk_level="low",
    )
    planner.plan.return_value = task_plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        operations_agent=operations_agent,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    ctx = ConversationContext(channel_id="C_MAIN", thread_ts="100.1", user_id="U_ALICE")
    ans = engine.ask(Question(text="Create task Deploy to Production", context=ctx))

    assert "Task created successfully" in ans.text
    assert "Deploy to Production" in ans.text
    assert ans.clear_pending is True
    operations_agent.process_event.assert_called_once()


# =========================================================================
# 20. Unrelated intents are not intercepted by calendar dispatch
# =========================================================================

def test_unrelated_intents_are_not_intercepted_by_calendar_dispatch(calendar_agent):
    pipeline = MagicMock()
    qa = MagicMock()
    expected_ans = Answer(text="Hello! How can I help you?", confidence=1.0)
    qa.answer.return_value = expected_ans
    planner = MagicMock()

    convo_plan = CognitivePlan(
        request_id="plan_convo",
        original_message="Hi there",
        intent=IntentCategory.GENERAL_CONVERSATION,
        intent_confidence=1.0,
        requested_outcome="Greet",
        entities=ExtractedEntities(),
        required_agents=[TargetAgent.GENERAL_REASONER],
        execution_steps=[],
        missing_information=[],
        requires_clarification=False,
        clarification_prompt=None,
        action_required=False,
        risk_level="low",
    )
    planner.plan.return_value = convo_plan

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=qa,
        calendar_agent=calendar_agent,
        planner=planner,
    )

    calendar_agent.execute_structured = MagicMock()
    calendar_agent.handle_message = MagicMock()

    q = Question(text="Hi there")
    ans = engine.ask(q)

    assert ans == expected_ans
    calendar_agent.execute_structured.assert_not_called()
    calendar_agent.handle_message.assert_not_called()
