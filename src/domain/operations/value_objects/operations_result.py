"""
Value object representing the result of an operational agent action.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.common.value_object import ValueObject
from domain.operations.entities import OperationalItem
from domain.operations.enums import OperationalItemStatus
from domain.organization.enums import OrganizationEventType


@dataclass(frozen=True, slots=True)
class OperationsResult(ValueObject):
    """
    Structured outcome of an Operations Agent processing step.
    
    Provides complete provenance, lifecycle transition details,
    affected operational item, and idempotency status.
    """

    event_type: OrganizationEventType
    operation: str
    item: OperationalItem | None = None
    status: OperationalItemStatus | None = None
    idempotent: bool = False
    affected_item_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    requires_action: bool = False
    is_overdue: bool = False
    correlation_id: str | None = None
