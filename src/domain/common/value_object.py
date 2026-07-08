"""
Base Value Object for the Polis Domain.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any
from dataclasses import asdict


@dataclass(frozen=True, slots=True)
class ValueObject(ABC):
    """
    Base class for immutable value objects.

    Value Objects:
    - Have no identity
    - Are immutable
    - Are compared by value
    """

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)