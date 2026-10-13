"""
Canonical organizational event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datetime import datetime

from domain.common.identifier import Identifier
from domain.common.value_object import ValueObject

from domain.organization.enums import (
    OrganizationEventType,
)

from domain.observation import (
    Observation,
)


@dataclass(frozen=True, slots=True)
class OrganizationEvent(ValueObject):
    """
    Represents a canonical business event
    that occurred inside the organization.
    """

    event_type: OrganizationEventType

    summary: str

    observations: list[Observation] = field(
        default_factory=list,
    )

    confidence: float = 1.0

    correlation_id: Identifier | None = None

    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("summary must not be empty")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0.0 and 1.0"
            )

        object.__setattr__(
            self,
            "observations",
            list(self.observations),
        )

        if isinstance(self.correlation_id, str):
            object.__setattr__(
                self,
                "correlation_id",
                Identifier(business_id=self.correlation_id),
            )
