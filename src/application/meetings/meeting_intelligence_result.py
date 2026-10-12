"""
Structured result produced by meeting-level intelligence.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MeetingIntelligenceResult:
    """
    Structured meeting-level intelligence.

    This is an application-layer result and does not replace
    canonical organizational events or operational items.
    """

    summary: str
    topics: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("summary must not be empty")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0.0 and 1.0"
            )

        object.__setattr__(
            self,
            "topics",
            list(self.topics),
        )
        object.__setattr__(
            self,
            "decisions",
            list(self.decisions),
        )
        object.__setattr__(
            self,
            "action_items",
            list(self.action_items),
        )
        object.__setattr__(
            self,
            "risks",
            list(self.risks),
        )
        object.__setattr__(
            self,
            "open_questions",
            list(self.open_questions),
        )
        object.__setattr__(
            self,
            "evidence",
            list(self.evidence),
        )
