from __future__ import annotations

from dataclasses import dataclass

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


@dataclass(frozen=True, slots=True)
class ReasoningContext:
    """
    Complete context used during reasoning.

    Today it only contains the communication.

    Later it will also contain organizational
    memory, governance, historical context,
    active projects, knowledge graph, etc.
    """

    communication: CommunicationEvent