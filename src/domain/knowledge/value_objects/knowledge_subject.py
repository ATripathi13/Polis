"""
Represents what a knowledge candidate is about.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class KnowledgeSubject(ValueObject):
    """
    The subject of a knowledge candidate.
    """

    kind: str

    identifier: str