"""
Command for ingesting a communication event.
"""

from __future__ import annotations

from dataclasses import dataclass

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


@dataclass(slots=True)
class IngestCommunicationCommand:
    """
    Command carrying a communication event
    into the application layer.
    """

    event: CommunicationEvent