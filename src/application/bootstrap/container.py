"""
Application container.
"""

from __future__ import annotations

from dataclasses import dataclass

from application.cognitive import (
    SimpleCognitiveEngine,
)

from application.activity import (
    ActivityProcessor,
    ActivityQuestionService,
)

from domain.activity import (
    ActivityService,
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

    activity_service: ActivityService

    activity_processor: ActivityProcessor

    activity_question_service: ActivityQuestionService