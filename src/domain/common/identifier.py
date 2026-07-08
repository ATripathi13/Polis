"""
Universal identifier model for Polis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class Identifier:
    """
    Immutable identity shared by every domain entity.
    """

    graph_id: UUID = field(default_factory=uuid4)

    business_id: str = ""