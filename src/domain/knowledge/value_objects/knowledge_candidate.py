"""
Represents a candidate piece of organizational knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.common.value_object import ValueObject

from domain.organization import (
    OrganizationEvent,
)
from .knowledge_subject import KnowledgeSubject


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate(ValueObject):
    """
    A potential piece of organizational
    knowledge awaiting validation.
    """

    subject: KnowledgeSubject

    summary: str

    supporting_events: list[OrganizationEvent] = field(
        default_factory=list,
    )

    confidence: float = 1.0