"""
Question Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class Question(ValueObject):
    """
    Represents a question asked to Polis.
    """

    text: str

    def __post_init__(self) -> None:

        if not self.text.strip():
            raise ValueError(
                "Question cannot be empty."
            )