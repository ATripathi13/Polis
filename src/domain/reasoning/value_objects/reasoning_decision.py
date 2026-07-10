from __future__ import annotations

from dataclasses import dataclass, field

from domain.reasoning.enums import ReasoningAction


@dataclass(frozen=True, slots=True)
class ReasoningDecision:
    """
    Result produced by the Reasoning Engine.
    """

    action: ReasoningAction

    confidence: float

    reason: str

    response: str | None = None

    evidence: list[str] = field(default_factory=list)