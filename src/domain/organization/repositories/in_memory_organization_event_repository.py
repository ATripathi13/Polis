from __future__ import annotations

from typing import Any

from domain.common.identifier import Identifier
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
        self._metadata: dict[
            tuple[str, str, OrganizationEventType],
            dict[str, Any],
        ] = {}

    def save(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | Identifier | None = None,
    ) -> None:
        if not source_type.strip():
            raise ValueError("source_type cannot be empty.")

        if not source_event_id.strip():
            raise ValueError("source_event_id cannot be empty.")

        key = (
            source_type,
            source_event_id,
            event.event_type,
        )

        if key not in self._events:
            self._events[key] = event
            corr = correlation_id or event.correlation_id
            self._metadata[key] = {
                "source_type": source_type,
                "source_event_id": source_event_id,
                "correlation_id": corr,
            }

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

    def find_by_source(
        self,
        source_type: str,
        source_event_id: str,
    ) -> list[OrganizationEvent]:
        return [
            event
            for (st, seid, _), event in self._events.items()
            if st == source_type and seid == source_event_id
        ]

    def find_by_correlation(
        self,
        correlation_id: str | Identifier,
    ) -> list[OrganizationEvent]:
        target = (
            correlation_id.business_id
            if isinstance(correlation_id, Identifier) and correlation_id.business_id
            else str(getattr(correlation_id, "graph_id", correlation_id))
        )
        results: list[OrganizationEvent] = []
        for key, event in self._events.items():
            meta_corr = self._metadata.get(key, {}).get("correlation_id")
            corr = meta_corr or event.correlation_id
            if corr is not None:
                corr_str = (
                    corr.business_id
                    if isinstance(corr, Identifier) and corr.business_id
                    else str(getattr(corr, "graph_id", corr))
                )
                if corr_str == target:
                    results.append(event)
        return results

    def all(self) -> list[OrganizationEvent]:
        return list(self._events.values())
