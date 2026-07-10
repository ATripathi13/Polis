from __future__ import annotations

from dataclasses import dataclass, field

from .observation import Observation


@dataclass(frozen=True, slots=True)
class ObservationBundle:
    """
    Collection of observations extracted
    from a single communication.
    """

    observations: list[Observation] = field(default_factory=list)