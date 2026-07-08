"""
Base Entity implementation for the Polis Domain.

Every business object in Polis inherits from Entity.
The domain layer contains no infrastructure dependencies.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from domain.common.identifier import Identifier


@dataclass(slots=True)
class Entity(ABC):
    """
    Base class for every domain entity.
    """

    identifier: Identifier = field(default_factory=Identifier)

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    deleted_at: datetime | None = None

    created_by: str = ""

    updated_by: str = ""

    metadata: dict[str, Any] = field(default_factory=dict)

    state: str = "ACTIVE"

    _domain_events: list[Any] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    @property
    def graph_id(self):
        return self.identifier.graph_id

    @property
    def business_id(self):
        return self.identifier.business_id

    def add_domain_event(self, event: Any) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[Any]:
        events = list(self._domain_events)
        self._domain_events.clear()
        return events

    def mark_deleted(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)

    def touch(self, updated_by: str = "") -> None:
        self.updated_at = datetime.now(timezone.utc)

        if updated_by:
            self.updated_by = updated_by

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return False

        return self.graph_id == other.graph_id

    def __hash__(self) -> int:
        return hash(self.graph_id)