"""
Base organizational event builder.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.observation import (
    ObservationBundle,
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
        bundle: ObservationBundle,
    ) -> list[OrganizationEvent]:
        """
        Build organizational events.
        """
        raise NotImplementedError