"""
Channel Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject

from .communication_identity import CommunicationIdentity


@dataclass(frozen=True, slots=True)
class Channel(ValueObject):
    """
    Represents the location where communication occurred.
    """

    identity: CommunicationIdentity

    name: str

    channel_type: str

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:

        if not self.name.strip():
            raise ValueError("name cannot be empty.")

        if not self.channel_type.strip():
            raise ValueError("channel_type cannot be empty.")