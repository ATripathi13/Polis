from __future__ import annotations

from datetime import datetime
from typing import Any

from domain.common.aggregate import AggregateRoot
from domain.common.identifier import Identifier

from ..enums import (
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
)


class OperationalItem(AggregateRoot):
    """
    Persistent operational intelligence item.

    One aggregate represents a TASK, DECISION, or RISK.
    """

    def __init__(
        self,
        *,
        identifier: Identifier,
        item_type: OperationalItemType,
        summary: str,
        status: OperationalItemStatus = OperationalItemStatus.OPEN,
        priority: OperationalItemPriority = OperationalItemPriority.MEDIUM,
        owner_id: str = "",
        owner_name: str = "",
        due_at: datetime | None = None,
        source_event_id: str = "",
        source_type: str = "",
        confidence: float = 1.0,
        evidence: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            identifier=identifier,
            metadata=dict(metadata or {}),
        )

        if not summary.strip():
            raise ValueError("summary must not be empty")

        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0.0 and 1.0"
            )

        self.item_type = item_type
        self.summary = summary
        self.status = status
        self.priority = priority
        self.owner_id = owner_id
        self.owner_name = owner_name
        self.due_at = due_at
        self.source_event_id = source_event_id
        self.source_type = source_type
        self.confidence = confidence
        self.evidence = list(evidence or [])

    @classmethod
    def create(
        cls,
        *,
        item_type: OperationalItemType,
        summary: str,
        status: OperationalItemStatus = OperationalItemStatus.OPEN,
        priority: OperationalItemPriority = OperationalItemPriority.MEDIUM,
        owner_id: str = "",
        owner_name: str = "",
        due_at: datetime | None = None,
        source_event_id: str = "",
        source_type: str = "",
        confidence: float = 1.0,
        evidence: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        business_id: str = "",
    ) -> "OperationalItem":
        return cls(
            identifier=Identifier(
                business_id=business_id,
            ),
            item_type=item_type,
            summary=summary,
            status=status,
            priority=priority,
            owner_id=owner_id,
            owner_name=owner_name,
            due_at=due_at,
            source_event_id=source_event_id,
            source_type=source_type,
            confidence=confidence,
            evidence=evidence,
            metadata=metadata,
        )
