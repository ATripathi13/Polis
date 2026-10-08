from datetime import datetime, timezone

import pytest

from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)


def test_create_task():
    due_at = datetime(
        2026,
        10,
        8,
        12,
        0,
        tzinfo=timezone.utc,
    )

    item = OperationalItem.create(
        item_type=OperationalItemType.TASK,
        summary="Prepare the weekly report",
        owner_id="U123",
        owner_name="John",
        due_at=due_at,
        source_event_id="1712345678.123456",
        source_type="slack",
        confidence=0.95,
        business_id="task-123",
    )

    assert item.item_type == OperationalItemType.TASK
    assert item.summary == "Prepare the weekly report"
    assert item.status == OperationalItemStatus.OPEN
    assert item.priority == OperationalItemPriority.MEDIUM
    assert item.owner_id == "U123"
    assert item.owner_name == "John"
    assert item.due_at == due_at
    assert item.source_event_id == "1712345678.123456"
    assert item.source_type == "slack"
    assert item.confidence == 0.95
    assert item.business_id == "task-123"


def test_create_decision():
    item = OperationalItem.create(
        item_type=OperationalItemType.DECISION,
        summary="Use PostgreSQL for the reporting database",
    )

    assert item.item_type == OperationalItemType.DECISION
    assert item.status == OperationalItemStatus.OPEN


def test_create_risk():
    item = OperationalItem.create(
        item_type=OperationalItemType.RISK,
        summary="LLM provider quota may interrupt processing",
        priority=OperationalItemPriority.HIGH,
    )

    assert item.item_type == OperationalItemType.RISK
    assert item.priority == OperationalItemPriority.HIGH


def test_empty_summary_is_rejected():
    with pytest.raises(ValueError, match="summary must not be empty"):
        OperationalItem.create(
            item_type=OperationalItemType.TASK,
            summary="   ",
        )


def test_invalid_confidence_is_rejected():
    with pytest.raises(
        ValueError,
        match="confidence must be between 0.0 and 1.0",
    ):
        OperationalItem.create(
            item_type=OperationalItemType.TASK,
            summary="Valid task",
            confidence=1.5,
        )
