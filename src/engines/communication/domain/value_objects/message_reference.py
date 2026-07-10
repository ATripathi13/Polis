"""
Message Reference Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class MessageReference(ValueObject):
    """
    Represents a relationship between two communication events.
    """

    reference_id: str

    relationship_type: str

    source: str

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:

        if not self.reference_id.strip():
            raise ValueError("reference_id cannot be empty.")

        if not self.relationship_type.strip():
            raise ValueError("relationship_type cannot be empty.")

        if not self.source.strip():
            raise ValueError("source cannot be empty.")