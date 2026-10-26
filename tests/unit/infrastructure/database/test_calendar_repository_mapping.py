from datetime import datetime, timezone
from uuid import UUID

from domain.common.identifier import Identifier
from infrastructure.database.calendar_repository import PostgreSQLCalendarRepository
from infrastructure.database.models import (
    CalendarEntryModel,
    CalendarReminderDeliveryModel,
)


def test_entry_mapping_preserves_database_id() -> None:
    stored_id = str(UUID("d4ed9510-ef0c-49a3-b228-176e02aa9d36"))
    now = datetime.now(timezone.utc)

    model = CalendarEntryModel(
        id=stored_id,
        title="Calendar mapping test",
        description="",
        entry_type="activity",
        creator_id="U_TEST",
        start_time=now,
        end_time=None,
        timezone="UTC",
        audience_type="individual",
        audience_id="U_TEST",
        status="scheduled",
        version=1,
        metadata_={},
        created_at=now,
        updated_at=now,
    )

    entry = PostgreSQLCalendarRepository._to_entry(model)

    assert entry.entry_id == stored_id
    assert entry.identifier.graph_id == UUID(stored_id)
    assert entry.identifier.business_id == stored_id


def test_delivery_mapping_preserves_database_id() -> None:
    stored_id = str(UUID("e4ed9510-ef0c-49a3-b228-176e02aa9d36"))
    entry_id = str(UUID("a4ed9510-ef0c-49a3-b228-176e02aa9d36"))
    now = datetime.now(timezone.utc)

    model = CalendarReminderDeliveryModel(
        id=stored_id,
        entry_id=entry_id,
        recipient_id="U_TEST",
        delivery_channel="dm",
        version=1,
        due_at=now,
        status="pending",
        attempt_count=0,
        last_attempt_at=None,
        sent_at=None,
        error_message=None,
        idempotency_key=f"cal-rem:{entry_id}:U_TEST:v1",
        created_at=now,
        updated_at=now,
    )

    delivery = PostgreSQLCalendarRepository._to_delivery(model)

    assert delivery.delivery_id == stored_id
    assert delivery.identifier.graph_id == UUID(stored_id)
    assert delivery.identifier.business_id == stored_id
