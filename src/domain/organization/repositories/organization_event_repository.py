from __future__ import annotations

from abc import ABC, abstractmethod

from domain.common.identifier import Identifier
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
        source_event_id: str | None = None,
        correlation_id: str | Identifier | None = None,
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

    def find_by_source(
        self,
        source_type: str,
        source_event_id: str,
    ) -> list[OrganizationEvent]:
        """
        Find all organizational events originating from a source event.
        """
        return []

    def find_by_correlation(
        self,
        correlation_id: str | Identifier,
    ) -> list[OrganizationEvent]:
        """
        Find all organizational events for an organizational correlation identity.
        """
        return []

    @abstractmethod
    def all(
        self,
    ) -> list[OrganizationEvent]:
        raise NotImplementedError
