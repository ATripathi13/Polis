from __future__ import annotations

from abc import ABC, abstractmethod

from domain.organization.enums import OrganizationEventType
from domain.organization.value_objects import OrganizationEvent


class OrganizationEventRepository(ABC):
    """
    Repository contract for persisted organizational events.

    OrganizationEvent remains an immutable value object.
    Source identity is supplied by the application boundary so
    persistence can enforce idempotency without coupling the
    domain value object to infrastructure concerns.
    """

    @abstractmethod
    def save(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_by_source_event(
        self,
        source_type: str,
        source_event_id: str,
        event_type: OrganizationEventType,
    ) -> OrganizationEvent | None:
        raise NotImplementedError

    @abstractmethod
    def all(
        self,
    ) -> list[OrganizationEvent]:
        raise NotImplementedError
