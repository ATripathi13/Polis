"""
Base organizational event builder.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.observation import (
    Observation,
)

from domain.organization.value_objects import (
    OrganizationEvent,
)


class OrganizationEventBuilder(ABC):
    """
    Converts observations into
    organizational events.
    """

    @abstractmethod
    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:
        """
        Build organizational events.
        """
        raise NotImplementedError