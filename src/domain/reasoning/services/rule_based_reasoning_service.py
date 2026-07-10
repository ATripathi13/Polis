"""
Rule-based reasoning engine.
"""

from __future__ import annotations

from domain.reasoning.enums import (
    ReasoningAction,
)

from domain.reasoning.registry import (
    ReasoningPolicyRegistry,
)

from domain.reasoning.services import (
    ReasoningService,
)

from domain.reasoning.value_objects import (
    ReasoningContext,
    ReasoningDecision,
)


class RuleBasedReasoningService(
    ReasoningService,
):
    """
    Executes reasoning policies in order.
    """

    def __init__(
        self,
        registry: ReasoningPolicyRegistry,
    ) -> None:
        self._registry = registry
    def reason(
        self,
        communication,
    ) -> ReasoningDecision:

        context = ReasoningContext(
            communication=communication,
        )

        for policy in self._registry.policies:

            decision = policy.evaluate(
                context,
            )

            if decision is not None:
                return decision

        return ReasoningDecision(
            action=ReasoningAction.IGNORE,
            confidence=1.0,
            reason="No reasoning policy matched.",
        )