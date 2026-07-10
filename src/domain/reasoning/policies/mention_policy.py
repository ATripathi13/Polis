"""
Reasoning policy for explicit mentions of Polis.
"""

from __future__ import annotations

from domain.reasoning.enums import (
    ReasoningAction,
)

from domain.reasoning.policies import (
    ReasoningPolicy,
)

from domain.reasoning.value_objects import (
    ReasoningContext,
    ReasoningDecision,
)


class MentionPolicy(
    ReasoningPolicy,
):
    """
    Fires when Polis is explicitly addressed.
    """

    def evaluate(
        self,
        context: ReasoningContext,
    ) -> ReasoningDecision | None:

        if not context.communication.is_addressed_to(
            "POLIS",
        ):
            return None

        return ReasoningDecision(
            action=ReasoningAction.REPLY,
            confidence=1.0,
            reason="Polis was explicitly mentioned.",
        )
    
    @property
    def priority(self) -> int:
        return 50