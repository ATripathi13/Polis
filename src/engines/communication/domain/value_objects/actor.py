"""
Actor Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject

from .communication_identity import CommunicationIdentity


@dataclass(frozen=True, slots=True)
class Actor(ValueObject):
    """
    Represents the initiator of a communication.
    """

    identity: CommunicationIdentity

    display_name: str

    email: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty.")