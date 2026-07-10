"""
Base observation extraction rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.observation.value_objects import (
    Observation,
)


class ObservationRule(ABC):
    """
    Base class for extracting organizational
    observations from a communication.
    """

    @property
    def priority(self) -> int:
        """
        Lower values execute first.
        """
        return 100

    @abstractmethod
    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:
        """
        Extract observations.
        """
        raise NotImplementedError