"""
Represents a source reference or evidence provenance for organizational knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class KnowledgeSourceReference(ValueObject):
    """
    Source traceability reference for a piece of knowledge.
    """

    source_type: str
    document_name: str | None = None
    source_event_id: str | None = None
    authority: str | None = None
    snippet: str = ""
