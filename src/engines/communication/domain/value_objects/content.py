"""
Content Value Object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.common.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class Content(ValueObject):
    """
    Represents normalized communication content.
    """

    body: str

    title: str | None = None

    language: str = "en"

    content_type: str = "text"

    summary: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:

        if not self.body.strip():
            raise ValueError("body cannot be empty.")

        if not self.language.strip():
            raise ValueError("language cannot be empty.")

        if not self.content_type.strip():
            raise ValueError("content_type cannot be empty.")