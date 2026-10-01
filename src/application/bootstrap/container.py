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
    MeetingRecordingProvider,
    TeamsSubscriptionService,
)

from domain.meetings import (
    TeamsSubscriptionRepository,
)

from domain.reminders import (
    ReminderRepository,
)

from domain.reminders.services import (
    ReminderService,
)

from application.knowledge_base import (
    KnowledgeBaseIngestionService,
)


@dataclass(slots=True)
class ApplicationContainer:
    """
    Holds the assembled POLIS application.
    """

    engine: SimpleCognitiveEngine

    knowledge_base_ingestion_service: KnowledgeBaseIngestionService
    repository: KnowledgeRepository

    activity_service: ActivityService

    activity_processor: ActivityProcessor

    activity_question_service: ActivityQuestionService

    meeting_transcript_service: MeetingTranscriptService

    meeting_transcript_provider: MeetingTranscriptProvider

    meeting_recording_provider: MeetingRecordingProvider

    teams_subscription_repository: TeamsSubscriptionRepository

    teams_subscription_service: TeamsSubscriptionService

    teams_recording_subscription_service: TeamsSubscriptionService

    reminder_repository: ReminderRepository

    reminder_service: ReminderService

