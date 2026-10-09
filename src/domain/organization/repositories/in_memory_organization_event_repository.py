from __future__ import annotations

from domain.organization.enums import OrganizationEventType
from domain.organization.value_objects import OrganizationEvent

from .organization_event_repository import OrganizationEventRepository


class InMemoryOrganizationEventRepository(
    OrganizationEventRepository,
):
    """
    In-memory repository for organizational events.
    """

    def __init__(self) -> None:
        self._events: dict[
            tuple[str, str, OrganizationEventType],
            OrganizationEvent,
        ] = {}

    def save(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
    ) -> None:
        key = (
            source_type,
            source_event_id,
            event.event_type,
        )

        if key not in self._events:
            self._events[key] = event

    def find_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
        event_type: OrganizationEventType,
    ) -> OrganizationEvent | None:
        return self._events.get(
            (
                source_type,
                source_event_id,
                event_type,
            )
        )

    def all(self) -> list[OrganizationEvent]:
        return list(self._events.values())
