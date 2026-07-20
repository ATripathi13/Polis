from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass(slots=True)
class KnowledgeRecord:

    id: str

    subject: str

    summary: str

    canonical_text: str

    confidence: float

    source: str

    created_at: datetime

    tags: list[str] = field(default_factory=list)

    embedding: list[float] | None = None

    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_validation(
        cls,
        validation_result,
        source: str = "Slack",
    ):

        candidate = validation_result.knowledge

        return cls(
            id=str(uuid4()),
            subject=candidate.subject.identifier,
            summary=candidate.summary,
            canonical_text=candidate.summary,
            confidence=candidate.confidence,
            source=source,
            created_at=datetime.utcnow(),
        )