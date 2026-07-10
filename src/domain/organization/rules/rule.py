"""
Base organizational event rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.observation import (
    Observation,
)

from domain.organization.value_objects import (
    OrganizationEvent,
)


class OrganizationEventRule(ABC):
    """
    Converts observations into
    organizational events.
    """

    @property
    def priority(self) -> int:
        """
        Lower values execute first.
        """
        return 100

    @abstractmethod
    def build(
        self,
        observations: list[Observation],
    ) -> list[OrganizationEvent]:
        """
        Build organizational events.
        """
        raise NotImplementedError