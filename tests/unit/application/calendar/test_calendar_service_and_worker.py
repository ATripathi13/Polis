"""
Unit tests for CalendarService and CalendarReminderWorker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from domain.calendar import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntryStatus,
    CalendarEntryType,
    CalendarReminderPolicy,
    InMemoryCalendarRepository,
    UnauthorizedCalendarActionError,
)
from application.calendar import (
    AudienceResolutionService,
    CalendarReminderWorker,
    CalendarService,
    SlackMembershipDirectoryProvider,
)


class MockSlackIdentityService:
    def resolve_user(self, name: str) -> dict | None:
        return {"id": name if name.startswith("U") else f"U_{name.upper()}", "name": name}

    def get_user_id(self, user: dict | None) -> str | None:
        return user.get("id") if user else None

    def get_workspace_users(self) -> list[dict]:
        return [{"id": "U_USER1"}, {"id": "U_USER2"}]


class MockSlackClient:
    def __init__(self, fail_for_users: list[str] | None = None) -> None:
        self.post_message_calls: list[dict] = []
        self.open_dm_calls: list[str] = []
        self.fail_for_users = fail_for_users or []

    def open_dm(self, user_id: str) -> str:
        self.open_dm_calls.append(user_id)
        if user_id in self.fail_for_users:
            raise RuntimeError(f"Slack API error for {user_id}")
        return f"D_{user_id}"

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> None:
        self.post_message_calls.append({
            "channel": channel,
            "text": text,
            "thread_ts": thread_ts,
        })
        if channel in self.fail_for_users or any(f"D_{u}" == channel for u in self.fail_for_users):
            raise RuntimeError(f"Slack postMessage failed for {channel}")


@pytest.fixture
def repo() -> InMemoryCalendarRepository:
    return InMemoryCalendarRepository()


@pytest.fixture
def audience_service() -> AudienceResolutionService:
    provider = SlackMembershipDirectoryProvider(
        slack_identity_service=MockSlackIdentityService(),
        team_roster_provider=lambda team: ["U_DEV1", "U_DEV2"] if team == "dev" else [],
    )
    return AudienceResolutionService(
        directory_provider=provider,
        organization_channel_id="C_MAIN",
    )


@pytest.fixture
def calendar_service(repo, audience_service) -> CalendarService:
    return CalendarService(
        repository=repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )


def test_create_calendar_entry_and_schedule_reminders(calendar_service, repo):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 11, 20, 10, 0, tzinfo=tz)

    entry = calendar_service.create_entry(
        title="Sprint Retrospective",
        description="End of sprint review",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET",
    )

    assert entry.title == "Sprint Retrospective"
    assert entry.creator_id == "U_CREATOR"
    assert entry.version == 1

    # Verify reminder delivery record was scheduled
    deliveries = repo.find_deliveries_for_entry(entry.entry_id)
    assert len(deliveries) == 1
    d = deliveries[0]
    assert d.recipient_id == "U_TARGET"
    assert d.status == CalendarDeliveryStatus.PENDING
    assert d.delivery_channel == "dm"
    # Due time must be exactly 15 hours before start
    assert d.due_at == start - timedelta(hours=15)
    assert d.idempotency_key == f"cal-rem:{entry.entry_id}:U_TARGET:v1"


def test_update_entry_reschedules_reminders_and_cancels_old(calendar_service, repo):
    tz = ZoneInfo("Asia/Kolkata")
    start1 = datetime(2026, 11, 20, 10, 0, tzinfo=tz)

    entry = calendar_service.create_entry(
        title="Product Launch",
        entry_type=CalendarEntryType.ANNOUNCEMENT,
        creator_id="U_CREATOR",
        start_time=start1,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET",
    )

    old_deliveries = repo.find_deliveries_for_entry(entry.entry_id)
    assert len(old_deliveries) == 1
    old_delivery_id = old_deliveries[0].delivery_id

    # Reschedule to 2 days later
    start2 = datetime(2026, 11, 22, 14, 0, tzinfo=tz)
    updated = calendar_service.update_entry(
        entry.entry_id,
        requester_id="U_CREATOR",
        start_time=start2,
    )

    assert updated.version == 2
    assert updated.start_time == start2

    # Old delivery must be cancelled
    old_delivery = repo.find_delivery(old_delivery_id)
    assert old_delivery.status == CalendarDeliveryStatus.CANCELLED

    # New delivery must be created for version 2 with new due time
    all_deliveries = repo.find_deliveries_for_entry(entry.entry_id)
    active_deliveries = [d for d in all_deliveries if d.status == CalendarDeliveryStatus.PENDING]
    assert len(active_deliveries) == 1
    new_delivery = active_deliveries[0]
    assert new_delivery.version == 2
    assert new_delivery.due_at == start2 - timedelta(hours=15)
    assert new_delivery.idempotency_key == f"cal-rem:{entry.entry_id}:U_TARGET:v2"


def test_unauthorized_user_cannot_update_or_cancel(calendar_service):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 11, 20, 10, 0, tzinfo=tz)

    entry = calendar_service.create_entry(
        title="Private Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_ALICE",
    )

    with pytest.raises(UnauthorizedCalendarActionError):
        calendar_service.update_entry(
            entry.entry_id,
            requester_id="U_BOB",
            title="Hacked Title",
        )

    with pytest.raises(UnauthorizedCalendarActionError):
        calendar_service.cancel_entry(
            entry.entry_id,
            requester_id="U_BOB",
        )

def test_only_creator_can_view_reminder_status(calendar_service, repo):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 11, 20, 10, 0, tzinfo=tz)

    entry = calendar_service.create_entry(
        title="Private Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET",
    )

    # The creator can inspect reminder delivery details.
    deliveries = calendar_service.get_reminder_status(
        entry.entry_id,
        requester_id="U_ALICE",
    )
    assert len(deliveries) == 1
    assert deliveries[0].recipient_id == "U_TARGET"

    # Another user must not see recipient-level delivery details.
    with pytest.raises(UnauthorizedCalendarActionError):
        calendar_service.get_reminder_status(
            entry.entry_id,
            requester_id="U_BOB",
        )


def test_reminder_status_rejects_missing_requester(calendar_service):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 11, 20, 10, 0, tzinfo=tz)

    entry = calendar_service.create_entry(
        title="Private Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ALICE",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET",
    )

    with pytest.raises(UnauthorizedCalendarActionError):
        calendar_service.get_reminder_status(
            entry.entry_id,
            requester_id="",
        )

def test_reminder_status_raises_for_missing_entry(calendar_service):
    from domain.calendar import CalendarEntryNotFoundError

    with pytest.raises(CalendarEntryNotFoundError):
        calendar_service.get_reminder_status(
            "nonexistent-entry",
            requester_id="U_ALICE",
        )

def test_cancel_entry_cancels_reminders(calendar_service, repo):
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 11, 20, 10, 0, tzinfo=tz)

    entry = calendar_service.create_entry(
        title="Town Hall",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_LEAD",
        start_time=start,
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET",
    )

    cancelled_entry = calendar_service.cancel_entry(entry.entry_id, requester_id="U_LEAD")
    assert cancelled_entry.status == CalendarEntryStatus.CANCELLED

    deliveries = repo.find_deliveries_for_entry(entry.entry_id)
    assert all(d.status == CalendarDeliveryStatus.CANCELLED for d in deliveries)


def test_calendar_reminder_worker_delivery_success(calendar_service, repo):
    tz = ZoneInfo("Asia/Kolkata")
    # Event scheduled 14 hours from now -> reminder was due 1 hour ago!
    now = datetime.now(timezone.utc)
    event_start = now + timedelta(hours=14)

    entry = calendar_service.create_entry(
        title="Board Meeting",
        description="Quarterly review with executives",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_EXEC",
        start_time=event_start.astimezone(tz),
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_DIRECTOR",
    )

    slack_client = MockSlackClient()
    worker = CalendarReminderWorker(
        repository=repo,
        slack_client=slack_client,
        poll_interval_seconds=30,
    )

    # Run delivery iteration
    sent = worker.poll_and_deliver(now=now)
    assert sent == 1

    # Verify Slack interactions
    assert "U_DIRECTOR" in slack_client.open_dm_calls
    assert len(slack_client.post_message_calls) == 1
    call = slack_client.post_message_calls[0]
    assert call["channel"] == "D_U_DIRECTOR"
    assert "Board Meeting" in call["text"]
    assert "15 hours" in call["text"]

    # Delivery marked SENT
    deliveries = repo.find_deliveries_for_entry(entry.entry_id)
    assert deliveries[0].status == CalendarDeliveryStatus.SENT
    assert deliveries[0].sent_at is not None

    # Repeated poll does not deliver again (exactly-once intent)
    sent_repeat = worker.poll_and_deliver(now=now)
    assert sent_repeat == 0
    assert len(slack_client.post_message_calls) == 1


def test_calendar_reminder_worker_handles_failure_without_blocking_others(calendar_service, repo):
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(timezone.utc)
    event_start = now + timedelta(hours=14)

    # Event for team (two recipients: U_DEV1 will fail, U_DEV2 will succeed)
    entry = calendar_service.create_entry(
        title="Dev Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_LEAD",
        start_time=event_start.astimezone(tz),
        audience_type=CalendarAudienceType.TEAM,
        audience_identifier="dev",
    )

    slack_client = MockSlackClient(fail_for_users=["U_DEV1"])
    worker = CalendarReminderWorker(
        repository=repo,
        slack_client=slack_client,
    )

    sent = worker.poll_and_deliver(now=now)
    assert sent == 1  # U_DEV2 succeeded!

    deliveries = repo.find_deliveries_for_entry(entry.entry_id)
    dev1_d = next(d for d in deliveries if d.recipient_id == "U_DEV1")
    dev2_d = next(d for d in deliveries if d.recipient_id == "U_DEV2")

    assert dev1_d.status == CalendarDeliveryStatus.FAILED
    assert "Slack API error" in dev1_d.error_message

    assert dev2_d.status == CalendarDeliveryStatus.SENT


def test_calendar_reminder_worker_skips_future_reminders(calendar_service, repo):
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(timezone.utc)
    # Event scheduled 20 hours from now -> reminder due in 5 hours!
    event_start = now + timedelta(hours=20)

    entry = calendar_service.create_entry(
        title="Future Conference",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=event_start.astimezone(tz),
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_TARGET",
    )

    slack_client = MockSlackClient()
    worker = CalendarReminderWorker(
        repository=repo,
        slack_client=slack_client,
    )

    sent = worker.poll_and_deliver(now=now)
    assert sent == 0
    assert len(slack_client.post_message_calls) == 0

    deliveries = repo.find_deliveries_for_entry(entry.entry_id)
    assert deliveries[0].status == CalendarDeliveryStatus.PENDING
