from domain.reasoning import (
    ReasoningAction,
    ReasoningDecision,
)


def test_reasoning_decision():

    decision = ReasoningDecision(
        action=ReasoningAction.IGNORE,
        confidence=1.0,
        reason="Normal knowledge update.",
    )

    assert decision.action == ReasoningAction.IGNORE
    assert decision.confidence == 1.0
    assert decision.response is None
    assert decision.evidence == []