"""
Knowledge Base document value object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class KnowledgeBaseDocument(ValueObject):
    """
    Represents a source document ingested into the POLIS Knowledge Base.
    """

    id: str
    name: str
    mime_type: str
    object_key: str
    checksum: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("id cannot be empty.")

        if not self.name.strip():
            raise ValueError("name cannot be empty.")

        if not self.mime_type.strip():
            raise ValueError("mime_type cannot be empty.")

        if not self.object_key.strip():
            raise ValueError("object_key cannot be empty.")

        if not self.checksum.strip():
            raise ValueError("checksum cannot be empty.")

        if not self.status.strip():
            raise ValueError("status cannot be empty.")