"""
Rule-based reasoning engine for POLIS.
"""

from __future__ import annotations

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.reasoning.enums import (
    ReasoningAction,
)

from domain.reasoning.services import (
    ReasoningService,
)

from domain.reasoning.value_objects import (
    ReasoningDecision,
)


class RuleBasedReasoningService(
    ReasoningService,
):
    """
    First implementation of the organizational
    reasoning engine.
    """

    def reason(
        self,
        communication: CommunicationEvent,
    ) -> ReasoningDecision:

        text = communication.content.body.lower()

        return ReasoningDecision(
            action=ReasoningAction.IGNORE,
            confidence=1.0,
            reason="No organizational action required.",
        )