"""
Dependency providers for the API.
"""

from __future__ import annotations

from application.cognitive import (
    SimpleCognitiveEngine,
)

from application.bootstrap import (
    get_container,
)

from domain.knowledge import (
    KnowledgeRepository,
)

from application.activity.activity_processor import (
    ActivityProcessor,
)


def get_cognitive_engine(
) -> SimpleCognitiveEngine:
    """
    Return the application's
    cognitive engine.
    """

    container = get_container()

    return container.engine


def get_repository(
) -> KnowledgeRepository:
    """
    Return the shared knowledge repository.
    """

    container = get_container()

    return container.repository


def get_activity_processor() -> ActivityProcessor:
    """
    Return the shared activity processor.
    """

    container = get_container()

    return container.activity_processor