from domain.observation import (
    Observation,
    ObservationType,
)
from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from domain.operations import (
    OperationalItemType,
)
from application.operations import (
    OperationalItemService,
)


class FakeOperationalItemRepository:
    def __init__(self):
        self.items = []

    def save(self, item):
        self.items.append(item)
        return item

    def find_by_source_event(
        self,
        source_type,
        source_event_id,
        item_type,
    ):
        for item in self.items:
            if (
                item.source_type == source_type
                and item.source_event_id == source_event_id
                and item.item_type == item_type
            ):
                return item
        return None


def make_event(
    event_type,
    observation_type,
    summary="Test operational item",
    source_event_id="slack-123",
):
    observation = Observation(
        observation_type=observation_type,
        summary=summary,
        confidence=0.9,
        evidence=[source_event_id],
    )

    return OrganizationEvent(
        event_type=event_type,
        summary=summary,
        observations=[observation],
        confidence=0.9,
    )


def test_task_event_creates_task():
    repository = FakeOperationalItemRepository()
    service = OperationalItemService(repository)

    item = service.process_event(
        make_event(
            OrganizationEventType.TASK_CREATED,
            ObservationType.TASK,
            "Prepare deployment report",
        ),
        source_type="slack",
    )

    assert item is not None
    assert item.item_type == OperationalItemType.TASK
    assert item.summary == "Prepare deployment report"
    assert item.source_type == "slack"
    assert item.source_event_id == "slack-123"


def test_decision_event_creates_decision():
    repository = FakeOperationalItemRepository()
    service = OperationalItemService(repository)

    item = service.process_event(
        make_event(
            OrganizationEventType.DECISION_MADE,
            ObservationType.DECISION,
            "Use PostgreSQL for operational storage",
        ),
        source_type="teams",
    )

    assert item is not None
    assert item.item_type == OperationalItemType.DECISION


def test_risk_event_creates_risk():
    repository = FakeOperationalItemRepository()
    service = OperationalItemService(repository)

    item = service.process_event(
        make_event(
            OrganizationEventType.RISK_IDENTIFIED,
            ObservationType.RISK,
            "Deployment may be delayed by the API dependency",
        ),
        source_type="teams",
    )

    assert item is not None
    assert item.item_type == OperationalItemType.RISK


def test_non_operational_event_is_ignored():
    repository = FakeOperationalItemRepository()
    service = OperationalItemService(repository)

    item = service.process_event(
        make_event(
            OrganizationEventType.KNOWLEDGE_DISCOVERED,
            ObservationType.KNOWLEDGE,
        ),
        source_type="slack",
    )

    assert item is None
    assert repository.items == []


def test_duplicate_source_event_is_not_created_twice():
    repository = FakeOperationalItemRepository()
    service = OperationalItemService(repository)

    event = make_event(
        OrganizationEventType.TASK_CREATED,
        ObservationType.TASK,
        "Prepare deployment report",
    )

    first = service.process_event(
        event,
        source_type="slack",
    )
    second = service.process_event(
        event,
        source_type="slack",
    )

    assert first is second
    assert len(repository.items) == 1
