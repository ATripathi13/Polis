"""
Represents a structured contradiction between knowledge sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class KnowledgeContradiction(ValueObject):
    """
    Detailed representation of conflicting organizational knowledge.
    """

    existing_knowledge: str
    new_knowledge: str
    conflict_explanation: str
    supporting_evidence: list[str] = field(default_factory=list)
    authority_info: dict[str, Any] = field(default_factory=dict)
    recommended_resolution: str = "escalate"
