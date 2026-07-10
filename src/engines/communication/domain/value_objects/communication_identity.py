"""
Communication Identity Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class CommunicationIdentity(ValueObject):
    """
    Canonical identity used within the Communication Engine.

    This object maps one Polis identity to one or more
    external connector identities.
    """

    internal_id: str

    external_ids: dict[str, str] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.internal_id.strip():
            raise ValueError("internal_id cannot be empty.")