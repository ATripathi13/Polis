"""
Domain aggregate representing a meeting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from domain.common.aggregate import AggregateRoot
from domain.common.identifier import Identifier


class Meeting(AggregateRoot):
    """
    Aggregate root representing a meeting.

    Meeting identity and metadata are kept here.
    Transcript and extracted intelligence are separate concerns.
    """

    def __init__(
        self,
        *,
        identifier: Identifier,
        external_id: str,
        title: str,
        source: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            identifier=identifier,
            metadata=dict(metadata or {}),
        )

        if not external_id.strip():
            raise ValueError("external_id must not be empty")

        if not title.strip():
            raise ValueError("title must not be empty")

        if not source.strip():
            raise ValueError("source must not be empty")

        self.external_id = external_id
        self.title = title
        self.source = source
        self.started_at = started_at
        self.ended_at = ended_at

    @classmethod
    def create(
        cls,
        *,
        external_id: str,
        title: str,
        source: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        business_id: str = "",
    ) -> Meeting:
        return cls(
            identifier=Identifier(
                business_id=business_id,
            ),
            external_id=external_id,
            title=title,
            source=source,
            started_at=started_at,
            ended_at=ended_at,
            metadata=metadata,
        )
