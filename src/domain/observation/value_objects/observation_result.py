"""
Result of an observation extraction.
"""

from __future__ import annotations

from dataclasses import dataclass

from .observation_bundle import ObservationBundle


@dataclass(frozen=True, slots=True)
class ObservationResult:
    """
    Represents the output of an observation extraction.
    """

    bundle: ObservationBundle

    extractor: str