from types import SimpleNamespace

import pytest

from domain.operations.enums import (
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)
from infrastructure.project_management.operational_item_provider import (
    OperationalItemProjectProvider,
)


class FakeRepository:
    def __init__(self, items):
        self.items = items

    def find_open(self):
        return self.items


def make_item(item_type, metadata=None):
    return SimpleNamespace(
        identifier=f"id-{item_type.value}",
        item_type=item_type,
        summary=f"Test {item_type.value}",
        status=OperationalItemStatus.OPEN,
        priority=OperationalItemPriority.HIGH,
        owner_id="",
        owner_name="",
        due_at=None,
        metadata=metadata or {},
        updated_at=None,
    )


@pytest.mark.parametrize(
    ("item_type", "expected_type"),
    [
        (OperationalItemType.TASK, "task"),
        (OperationalItemType.DECISION, "decision"),
        (OperationalItemType.RISK, "risk"),
    ],
)
def test_preserves_operational_item_type(item_type, expected_type):
    provider = OperationalItemProjectProvider(
        FakeRepository([make_item(item_type)])
    )

    result = provider.get_work_items()

    assert len(result) == 1
    assert result[0].item_type == expected_type
    assert result[0].is_overarching is False


def test_explicit_initiative_metadata_marks_item_overarching():
    item = make_item(
        OperationalItemType.TASK,
        {"is_overarching": True},
    )
    provider = OperationalItemProjectProvider(FakeRepository([item]))

    result = provider.get_work_items()

    assert result[0].item_type == "initiative"
    assert result[0].is_overarching is True


def test_explicit_sprint_metadata_is_preserved():
    item = make_item(
        OperationalItemType.TASK,
        {
            "sprint_id": "sprint-42",
            "sprint_name": "Hardening Sprint",
        },
    )
    provider = OperationalItemProjectProvider(FakeRepository([item]))

    result = provider.get_work_items()

    assert result[0].sprint_id == "sprint-42"
    assert result[0].sprint_name == "Hardening Sprint"


def test_missing_sprint_metadata_does_not_invent_sprint():
    provider = OperationalItemProjectProvider(
        FakeRepository([make_item(OperationalItemType.TASK)])
    )

    result = provider.get_work_items()

    assert result[0].sprint_id is None
    assert result[0].sprint_name is None
    assert provider.get_active_sprints() == []
