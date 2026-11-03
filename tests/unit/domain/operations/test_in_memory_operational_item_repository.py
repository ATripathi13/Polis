from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from domain.operations import (
    InMemoryOperationalItemRepository,
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)

@pytest.fixture
def repo() -> InMemoryOperationalItemRepository:
    return InMemoryOperationalItemRepository()


def make_test_item(
    *,
    item_type: OperationalItemType = OperationalItemType.TASK,
    summary: str = "Test operational item",
    status: OperationalItemStatus = OperationalItemStatus.OPEN,
    priority: OperationalItemPriority = OperationalItemPriority.MEDIUM,
    owner_id: str = "user-alice",
    owner_name: str = "Alice Smith",
    due_at: datetime | None = None,
    created_at: datetime | None = None,
    source_event_id: str | None = None,
) -> OperationalItem:
    item = OperationalItem.create(
        item_type=item_type,
        summary=summary,
        status=status,
        priority=priority,
        owner_id=owner_id,
        owner_name=owner_name,
        due_at=due_at,
        source_event_id=source_event_id or f"test-evt-{uuid4()}",
        source_type="test-slack",
    )
    if created_at is not None:
        item.created_at = created_at
    return item


# =============================================================================
# A. find_open_for_owner_or_name
# =============================================================================


def test_find_open_matches_by_owner_id(repo: InMemoryOperationalItemRepository) -> None:
    item = make_test_item(
        summary="Task by owner ID",
        owner_id="target-user-1",
        owner_name="Unrelated Name",
    )
    repo.save(item)

    results = repo.find_open_for_owner_or_name(
        owner_id="target-user-1",
        owner_name="Expected Name",
    )

    assert len(results) == 1
    assert results[0].identifier.graph_id == item.identifier.graph_id


def test_find_open_matches_by_owner_name(repo: InMemoryOperationalItemRepository) -> None:
    item = make_test_item(
        summary="Task by owner name",
        owner_id="unrelated-user-99",
        owner_name="Target Name",
    )
    repo.save(item)

    results = repo.find_open_for_owner_or_name(
        owner_id="expected-id-1",
        owner_name="Target Name",
    )

    assert len(results) == 1
    assert results[0].identifier.graph_id == item.identifier.graph_id


def test_find_open_excludes_unrelated_owners(
    repo: InMemoryOperationalItemRepository,
) -> None:
    unrelated_item = make_test_item(
        summary="Unrelated task",
        owner_id="bob-id",
        owner_name="Bob Jones",
    )
    repo.save(unrelated_item)

    results = repo.find_open_for_owner_or_name(
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert results == []


def test_find_open_excludes_completed_and_cancelled_items(
    repo: InMemoryOperationalItemRepository,
) -> None:
    open_item = make_test_item(
        summary="Open task",
        status=OperationalItemStatus.OPEN,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    in_progress_item = make_test_item(
        summary="In progress task",
        status=OperationalItemStatus.IN_PROGRESS,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    completed_item = make_test_item(
        summary="Completed task",
        status=OperationalItemStatus.COMPLETED,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    cancelled_item = make_test_item(
        summary="Cancelled task",
        status=OperationalItemStatus.CANCELLED,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    closed_item = make_test_item(
        summary="Closed task",
        status=OperationalItemStatus.CLOSED,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    for it in (open_item, in_progress_item, completed_item, cancelled_item, closed_item):
        repo.save(it)

    results = repo.find_open_for_owner_or_name(
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    returned_ids = {r.identifier.graph_id for r in results}
    assert returned_ids == {
        open_item.identifier.graph_id,
        in_progress_item.identifier.graph_id,
    }


def test_find_open_includes_all_item_types_when_item_type_none(
    repo: InMemoryOperationalItemRepository,
) -> None:
    task_item = make_test_item(
        item_type=OperationalItemType.TASK,
        summary="A task item",
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    decision_item = make_test_item(
        item_type=OperationalItemType.DECISION,
        summary="A decision item",
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    risk_item = make_test_item(
        item_type=OperationalItemType.RISK,
        summary="A risk item",
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    for it in (task_item, decision_item, risk_item):
        repo.save(it)

    results = repo.find_open_for_owner_or_name(
        owner_id="alice-id",
        owner_name="Alice Smith",
        item_type=None,
    )

    assert len(results) == 3
    types = {r.item_type for r in results}
    assert types == {
        OperationalItemType.TASK,
        OperationalItemType.DECISION,
        OperationalItemType.RISK,
    }


def test_find_open_filters_by_item_type_task(
    repo: InMemoryOperationalItemRepository,
) -> None:
    task_item = make_test_item(
        item_type=OperationalItemType.TASK,
        summary="A task item",
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    decision_item = make_test_item(
        item_type=OperationalItemType.DECISION,
        summary="A decision item",
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    repo.save(task_item)
    repo.save(decision_item)

    results = repo.find_open_for_owner_or_name(
        owner_id="alice-id",
        owner_name="Alice Smith",
        item_type=OperationalItemType.TASK,
    )

    assert len(results) == 1
    assert results[0].identifier.graph_id == task_item.identifier.graph_id


def test_find_open_returns_item_matching_both_conditions_only_once(
    repo: InMemoryOperationalItemRepository,
) -> None:
    item = make_test_item(
        summary="Both ID and Name match",
        owner_id="alice-id",
        owner_name="Alice Smith",
    )
    repo.save(item)

    results = repo.find_open_for_owner_or_name(
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 1
    assert results[0].identifier.graph_id == item.identifier.graph_id


def test_find_open_sorts_by_created_at_descending(
    repo: InMemoryOperationalItemRepository,
) -> None:
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)

    item1 = make_test_item(summary="Oldest", created_at=t1, owner_id="alice-id")
    item2 = make_test_item(summary="Newest", created_at=t2, owner_id="alice-id")
    item3 = make_test_item(summary="Middle", created_at=t3, owner_id="alice-id")

    repo.save(item1)
    repo.save(item2)
    repo.save(item3)

    results = repo.find_open_for_owner_or_name(
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 3
    assert [r.summary for r in results] == ["Newest", "Middle", "Oldest"]


# =============================================================================
# B. find_overdue_for_owner_or_name
# =============================================================================


def test_find_overdue_matches_by_owner_id_and_owner_name(
    repo: InMemoryOperationalItemRepository,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    item_by_id = make_test_item(
        summary="Overdue by ID",
        owner_id="alice-id",
        owner_name="Different Name",
        due_at=now - timedelta(hours=2),
    )
    item_by_name = make_test_item(
        summary="Overdue by Name",
        owner_id="different-id",
        owner_name="Alice Smith",
        due_at=now - timedelta(hours=1),
    )

    repo.save(item_by_id)
    repo.save(item_by_name)

    results = repo.find_overdue_for_owner_or_name(
        now,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 2
    ids = {r.identifier.graph_id for r in results}
    assert ids == {
        item_by_id.identifier.graph_id,
        item_by_name.identifier.graph_id,
    }


def test_find_overdue_excludes_unrelated_owners(
    repo: InMemoryOperationalItemRepository,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    item = make_test_item(
        summary="Bob's overdue item",
        owner_id="bob-id",
        owner_name="Bob Jones",
        due_at=now - timedelta(days=1),
    )
    repo.save(item)

    results = repo.find_overdue_for_owner_or_name(
        now,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert results == []


def test_find_overdue_includes_open_and_in_progress_only(
    repo: InMemoryOperationalItemRepository,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    past_due = now - timedelta(days=1)

    open_item = make_test_item(
        summary="Open overdue",
        status=OperationalItemStatus.OPEN,
        due_at=past_due,
        owner_id="alice-id",
    )
    in_progress_item = make_test_item(
        summary="In progress overdue",
        status=OperationalItemStatus.IN_PROGRESS,
        due_at=past_due,
        owner_id="alice-id",
    )
    completed_item = make_test_item(
        summary="Completed overdue",
        status=OperationalItemStatus.COMPLETED,
        due_at=past_due,
        owner_id="alice-id",
    )
    cancelled_item = make_test_item(
        summary="Cancelled overdue",
        status=OperationalItemStatus.CANCELLED,
        due_at=past_due,
        owner_id="alice-id",
    )

    for it in (open_item, in_progress_item, completed_item, cancelled_item):
        repo.save(it)

    results = repo.find_overdue_for_owner_or_name(
        now,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    ids = {r.identifier.graph_id for r in results}
    assert ids == {
        open_item.identifier.graph_id,
        in_progress_item.identifier.graph_id,
    }


def test_find_overdue_excludes_missing_due_dates(
    repo: InMemoryOperationalItemRepository,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    item = make_test_item(
        summary="No due date",
        due_at=None,
        owner_id="alice-id",
    )
    repo.save(item)

    results = repo.find_overdue_for_owner_or_name(
        now,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert results == []


def test_find_overdue_boundary_strictly_before_now(
    repo: InMemoryOperationalItemRepository,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    strictly_before = make_test_item(
        summary="Before now",
        due_at=now - timedelta(seconds=1),
        owner_id="alice-id",
    )
    exactly_now = make_test_item(
        summary="Exactly now",
        due_at=now,
        owner_id="alice-id",
    )
    strictly_after = make_test_item(
        summary="After now",
        due_at=now + timedelta(seconds=1),
        owner_id="alice-id",
    )

    repo.save(strictly_before)
    repo.save(exactly_now)
    repo.save(strictly_after)

    results = repo.find_overdue_for_owner_or_name(
        now,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 1
    assert results[0].identifier.graph_id == strictly_before.identifier.graph_id


def test_find_overdue_sorts_by_due_at_ascending(
    repo: InMemoryOperationalItemRepository,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    item1 = make_test_item(
        summary="Due 3 days ago",
        due_at=now - timedelta(days=3),
        owner_id="alice-id",
    )
    item2 = make_test_item(
        summary="Due 1 day ago",
        due_at=now - timedelta(days=1),
        owner_id="alice-id",
    )
    item3 = make_test_item(
        summary="Due 5 days ago",
        due_at=now - timedelta(days=5),
        owner_id="alice-id",
    )

    repo.save(item1)
    repo.save(item2)
    repo.save(item3)

    results = repo.find_overdue_for_owner_or_name(
        now,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 3
    assert [r.summary for r in results] == [
        "Due 5 days ago",
        "Due 3 days ago",
        "Due 1 day ago",
    ]


# =============================================================================
# C. find_due_between_for_owner_or_name
# =============================================================================


def test_find_due_between_matches_by_owner_id_and_owner_name(
    repo: InMemoryOperationalItemRepository,
) -> None:
    start = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)

    item_id = make_test_item(
        summary="Due in window by ID",
        owner_id="alice-id",
        owner_name="Other Name",
        due_at=datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    item_name = make_test_item(
        summary="Due in window by Name",
        owner_id="other-id",
        owner_name="Alice Smith",
        due_at=datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc),
    )

    repo.save(item_id)
    repo.save(item_name)

    results = repo.find_due_between_for_owner_or_name(
        start,
        end,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 2
    ids = {r.identifier.graph_id for r in results}
    assert ids == {
        item_id.identifier.graph_id,
        item_name.identifier.graph_id,
    }


def test_find_due_between_excludes_unrelated_owners_and_non_open_statuses(
    repo: InMemoryOperationalItemRepository,
) -> None:
    start = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    due_date = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)

    bob_item = make_test_item(
        summary="Bob's task in window",
        owner_id="bob-id",
        owner_name="Bob Jones",
        due_at=due_date,
    )
    completed_item = make_test_item(
        summary="Completed task in window",
        status=OperationalItemStatus.COMPLETED,
        owner_id="alice-id",
        owner_name="Alice Smith",
        due_at=due_date,
    )
    cancelled_item = make_test_item(
        summary="Cancelled task in window",
        status=OperationalItemStatus.CANCELLED,
        owner_id="alice-id",
        owner_name="Alice Smith",
        due_at=due_date,
    )

    for it in (bob_item, completed_item, cancelled_item):
        repo.save(it)

    results = repo.find_due_between_for_owner_or_name(
        start,
        end,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert results == []


def test_find_due_between_excludes_missing_due_dates(
    repo: InMemoryOperationalItemRepository,
) -> None:
    start = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)

    item = make_test_item(
        summary="No due date",
        due_at=None,
        owner_id="alice-id",
    )
    repo.save(item)

    results = repo.find_due_between_for_owner_or_name(
        start,
        end,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert results == []


def test_find_due_between_inclusive_boundaries(
    repo: InMemoryOperationalItemRepository,
) -> None:
    start = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    before_start = make_test_item(
        summary="1s before start",
        due_at=start - timedelta(seconds=1),
        owner_id="alice-id",
    )
    at_start = make_test_item(
        summary="Exactly at start",
        due_at=start,
        owner_id="alice-id",
    )
    inside_window = make_test_item(
        summary="Inside window",
        due_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        owner_id="alice-id",
    )
    at_end = make_test_item(
        summary="Exactly at end",
        due_at=end,
        owner_id="alice-id",
    )
    after_end = make_test_item(
        summary="1s after end",
        due_at=end + timedelta(seconds=1),
        owner_id="alice-id",
    )

    for it in (before_start, at_start, inside_window, at_end, after_end):
        repo.save(it)

    results = repo.find_due_between_for_owner_or_name(
        start,
        end,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    ids = {r.identifier.graph_id for r in results}
    assert ids == {
        at_start.identifier.graph_id,
        inside_window.identifier.graph_id,
        at_end.identifier.graph_id,
    }


def test_find_due_between_accepts_start_equal_end(
    repo: InMemoryOperationalItemRepository,
) -> None:
    point = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)

    exact_item = make_test_item(
        summary="Exact point item",
        due_at=point,
        owner_id="alice-id",
    )
    other_item = make_test_item(
        summary="Slightly later item",
        due_at=point + timedelta(seconds=1),
        owner_id="alice-id",
    )

    repo.save(exact_item)
    repo.save(other_item)

    results = repo.find_due_between_for_owner_or_name(
        point,
        point,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 1
    assert results[0].identifier.graph_id == exact_item.identifier.graph_id


def test_find_due_between_raises_value_error_when_start_after_end(
    repo: InMemoryOperationalItemRepository,
) -> None:
    start = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="start.*must not be after end"):
        repo.find_due_between_for_owner_or_name(
            start,
            end,
            owner_id="alice-id",
            owner_name="Alice Smith",
        )


def test_find_due_between_sorts_by_due_at_ascending(
    repo: InMemoryOperationalItemRepository,
) -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)

    item_day5 = make_test_item(
        summary="Day 5",
        due_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        owner_id="alice-id",
    )
    item_day1 = make_test_item(
        summary="Day 1",
        due_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        owner_id="alice-id",
    )
    item_day10 = make_test_item(
        summary="Day 10",
        due_at=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
        owner_id="alice-id",
    )

    repo.save(item_day5)
    repo.save(item_day1)
    repo.save(item_day10)

    results = repo.find_due_between_for_owner_or_name(
        start,
        end,
        owner_id="alice-id",
        owner_name="Alice Smith",
    )

    assert len(results) == 3
    assert [r.summary for r in results] == ["Day 1", "Day 5", "Day 10"]
