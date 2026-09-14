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

from application.meetings import (
    MeetingTranscriptService,
    MeetingTranscriptProvider,
    TeamsSubscriptionService,
)

from domain.meetings import (
    TeamsSubscriptionRepository,
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

    meeting_transcript_service: MeetingTranscriptService

    meeting_transcript_provider: MeetingTranscriptProvider

    teams_subscription_repository: TeamsSubscriptionRepository

    teams_subscription_service: TeamsSubscriptionService