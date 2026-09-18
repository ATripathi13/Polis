from __future__ import annotations

from dataclasses import dataclass

from domain.common.value_object import ValueObject
from .conversation_context import ConversationContext


@dataclass(frozen=True, slots=True)
class Question(ValueObject):
    """
    Represents a question asked to Polis.
    """

    text: str
    context: ConversationContext | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError(
                "Question cannot be empty."
            )