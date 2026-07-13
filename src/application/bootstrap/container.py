"""
Application container.
"""

from __future__ import annotations

from dataclasses import dataclass

from application.cognitive import (
    SimpleCognitiveEngine,
)

from domain.knowledge import (
    KnowledgeRepository,
)


@dataclass(slots=True)
class ApplicationContainer:
    """
    Holds the assembled POLIS application.
    """

    engine: SimpleCognitiveEngine

    repository: KnowledgeRepository