"""
Knowledge Base chunk value object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class KnowledgeBaseChunk(ValueObject):
    """
    Represents one searchable chunk of a Knowledge Base document.
    """

    id: str
    document_id: str
    chunk_index: int
    content: str
    qdrant_point_id: str
    page_number: int | None = None
    section_title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("id cannot be empty.")

        if not self.document_id.strip():
            raise ValueError("document_id cannot be empty.")

        if self.chunk_index < 0:
            raise ValueError("chunk_index cannot be negative.")

        if not self.content.strip():
            raise ValueError("content cannot be empty.")

        if not self.qdrant_point_id.strip():
            raise ValueError("qdrant_point_id cannot be empty.")