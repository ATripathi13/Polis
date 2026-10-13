"""
Canonical organizational observation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.common.identifier import Identifier
from domain.common.value_object import ValueObject

from domain.observation.enums import ObservationType


@dataclass(frozen=True, slots=True)
class Observation(ValueObject):
    """
    A normalized organizational observation.

    This is the canonical language spoken by
    every Polis engine.
    """

    observation_type: ObservationType

    summary: str

    confidence: float = 1.0

    evidence: list[str] = field(default_factory=list)

    correlation_id: Identifier | None = None

    occurred_at: datetime | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence",
            list(self.evidence),
        )
        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata),
        )
        if isinstance(self.correlation_id, str):
            object.__setattr__(
                self,
                "correlation_id",
                Identifier(business_id=self.correlation_id),
            )