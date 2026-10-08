from datetime import datetime, timedelta, timezone

from application.operations import OperationalItemService
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from domain.reasoning import Question


class FakeOperationalRepository:
    def __init__(self, items):
        self.items = items

    def find_open(self, *, item_type=None, owner_id=None):
        return [
            item for item in self.items
            if item.status in {
                OperationalItemStatus.OPEN,
                OperationalItemStatus.IN_PROGRESS,
            }
            and (item_type is None or item.item_type == item_type)
            and (owner_id is None or item.owner_id == owner_id)
        ]

    def find_overdue(self, now):
        return [
            item for item in self.items
            if item.due_at is not None
            and item.due_at < now
            and item.status in {
                OperationalItemStatus.OPEN,
                OperationalItemStatus.IN_PROGRESS,
            }
        ]


def make_item(item_type, summary, status=OperationalItemStatus.OPEN, due_at=None):
    return OperationalItem.create(
        item_type=item_type,
        summary=summary,
        status=status,
        priority=OperationalItemPriority.MEDIUM,
        due_at=due_at,
        source_event_id="test-event",
        source_type="test",
    )


def test_retrieve_task_evidence():
    service = OperationalItemService(
        FakeOperationalRepository([
            make_item(
                OperationalItemType.TASK,
                "Prepare deployment report",
            ),
        ])
    )

    evidence = service.retrieve_evidence(
        Question(text="What tasks are open?")
    )

    assert len(evidence) == 1
    assert "Prepare deployment report" in evidence[0]
    assert "Operational item: task" in evidence[0]


def test_retrieve_decision_evidence():
    service = OperationalItemService(
        FakeOperationalRepository([
            make_item(
                OperationalItemType.DECISION,
                "Use PostgreSQL for operational storage",
            ),
        ])
    )

    evidence = service.retrieve_evidence(
        Question(text="What decisions were made?")
    )

    assert len(evidence) == 1
    assert "Use PostgreSQL for operational storage" in evidence[0]


def test_retrieve_risk_evidence():
    service = OperationalItemService(
        FakeOperationalRepository([
            make_item(
                OperationalItemType.RISK,
                "Deployment may be delayed",
            ),
        ])
    )

    evidence = service.retrieve_evidence(
        Question(text="What risks were identified?")
    )

    assert len(evidence) == 1
    assert "Deployment may be delayed" in evidence[0]


def test_retrieve_overdue_evidence():
    now = datetime.now(timezone.utc)

    service = OperationalItemService(
        FakeOperationalRepository([
            make_item(
                OperationalItemType.TASK,
                "Overdue deployment task",
                due_at=now - timedelta(hours=2),
            ),
        ])
    )

    evidence = service.retrieve_evidence(
        Question(text="What tasks are overdue?")
    )

    assert len(evidence) == 1
    assert "Overdue deployment task" in evidence[0]
