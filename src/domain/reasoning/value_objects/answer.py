"""
Answer Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass, field


from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class Answer(ValueObject):
    """
    Answer returned by Polis.
    """

    text: str

    confidence: float = 1.0

    evidence: list[str] = field(
        default_factory=list,
    )

    def __post_init__(self) -> None:

        if not self.text.strip():
            raise ValueError(
                "Answer cannot be empty."
            )