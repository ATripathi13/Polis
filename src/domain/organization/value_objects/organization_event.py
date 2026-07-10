"""
Canonical organizational event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    Represents a business event
    that occurred inside the organization.
    """

    event_type: OrganizationEventType

    summary: str

    observations: list[Observation] = field(
        default_factory=list,
    )

    confidence: float = 1.0