from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from domain.common.identifier import Identifier

from domain.common.aggregate import AggregateRoot

from ..enums import ActivitySource, ActivityType


@dataclass(slots=True, kw_only=True)
class ActivityEvent(AggregateRoot):
    """
    Represents an observed work/activity event for a person.
    """

    person_id: str
    person_name: str

    activity_type: ActivityType
    occurred_at: datetime

    source: ActivitySource

    source_event_id: str | None = None

    break_type: str | None = None

    note: str | None = None

    @classmethod
    def create(
        cls,
        *,
        person_id: str,
        person_name: str,
        activity_type: ActivityType,
        occurred_at: datetime,
        source: ActivitySource,
        source_event_id: str | None = None,
        break_type: str | None = None,
        note: str | None = None,
    ) -> "ActivityEvent":
        """
        Create a validated activity event.
        """

        if not person_id.strip():
            raise ValueError(
                "person_id cannot be empty."
            )

        if not person_name.strip():
            raise ValueError(
                "person_name cannot be empty."
            )

        return cls(
            identifier=Identifier(),
            person_id=person_id,
            person_name=person_name,
            activity_type=activity_type,
            occurred_at=occurred_at,
            source=source,
            source_event_id=source_event_id,
            break_type=break_type,
            note=note,
        )
