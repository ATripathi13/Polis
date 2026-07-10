"""
Attachment Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class Attachment(ValueObject):
    """
    Represents an attachment associated with a communication.
    """

    attachment_id: str

    filename: str

    mime_type: str

    size_bytes: int

    url: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:

        if not self.attachment_id.strip():
            raise ValueError("attachment_id cannot be empty.")

        if not self.filename.strip():
            raise ValueError("filename cannot be empty.")

        if not self.mime_type.strip():
            raise ValueError("mime_type cannot be empty.")

        if self.size_bytes < 0:
            raise ValueError("size_bytes cannot be negative.")