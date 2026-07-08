"""
Base Domain Event.

Every business event inside Polis inherits from this class.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class DomainEvent(ABC):
    """
    Base class for all domain events.
    """

    event_id: UUID = field(default_factory=uuid4)

    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    event_type: str = ""