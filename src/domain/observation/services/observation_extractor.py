"""
Base observation extractor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.observation.value_objects import (
    Observation,
)


class ObservationExtractor(ABC):
    """
    Converts communications into
    organizational observations.
    """

    @abstractmethod
    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:
        """
        Produce observations from
        a communication.
        """
        raise NotImplementedError