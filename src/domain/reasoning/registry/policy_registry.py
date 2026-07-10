"""
Registry for reasoning policies.
"""

from __future__ import annotations

from domain.reasoning.policies import (
    ReasoningPolicy,
)


class ReasoningPolicyRegistry:
    """
    Stores reasoning policies in execution order.
    """

    def __init__(self) -> None:
        self._policies: list[ReasoningPolicy] = []

    def register(
        self,
        policy: ReasoningPolicy,
    ) -> None:
        """
        Register a reasoning policy.
        """
        self._policies.append(policy)

        self._policies.sort(
            key=lambda p: p.priority,
        )

    @property
    def policies(
        self,
    ) -> list[ReasoningPolicy]:
        """
        Registered policies.
        """
        return self._policies