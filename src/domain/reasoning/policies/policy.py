"""
Base interface for reasoning policies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.reasoning.value_objects import (
    ReasoningDecision,
)


class ReasoningPolicy(ABC):
    """
    Base reasoning policy.

    A policy may decide to act or
    choose not to apply.
    """

    @abstractmethod
    def evaluate(
        self,
        context: ReasoningContext
    ) -> ReasoningDecision | None:
        """
        Return a decision or None if the
        policy does not apply.
        """
        raise NotImplementedError
    
    @property
    def priority(self) -> int:
        """
        Lower values execute first.
        """
        return 100