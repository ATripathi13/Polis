"""
Canonical organizational observation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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