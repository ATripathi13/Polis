from dataclasses import dataclass

from domain.common.event import DomainEvent


@dataclass(frozen=True, slots=True)
class DummyEvent(DomainEvent):
    event_type: str = "dummy"


def test_domain_event() -> None:
    event = DummyEvent()

    assert event.event_type == "dummy"

    assert event.event_id is not None