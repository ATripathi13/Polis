"""
Application bootstrap.
"""

from __future__ import annotations


from infrastructure.llm.knowledge_understanding import (
    LLMKnowledgeUnderstanding,
)
from infrastructure.llm.operational_understanding import (
    LLMOperationalUnderstanding,
)
from infrastructure.llm.organizational_intent_understanding import (
    LLMOrganizationalIntentUnderstanding,
)
from infrastructure.vector import (
    QdrantKnowledgeBaseRepository,
)

from infrastructure.storage import (
    MinIOKnowledgeBaseStorage,
)
from application.cognitive import (
    SimpleCognitiveEngine,
)

from application.activity import (
    ActivityDetector,
    ActivityProcessor,
    ActivityQuestionService,
    AttendanceCalculator,
)

from .container import (
    ApplicationContainer,
)
from application.pipeline.pipeline import (
    PolisPipeline,
)
from application.services.knowledge_acceptance_service import (
    KnowledgeAcceptanceService,
)
from application.operations import (
    OperationalItemService,
    OperationsAgent,
)
from application.knowledge import (
    KnowledgeAgent,
)
from application.governance import (
    GovernanceAgent,
)

from domain.knowledge import (
    KnowledgeDiscoveryRule,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)

from application.activity import (
    ActivityDetector,
    ActivityProcessor,
    ActivityQuestionService,
    ActivityService,
    AttendanceCalculator,
)

from infrastructure.database import (
    PostgreSQLKnowledgeRepository,
    PostgreSQLActivityRepository,
    PostgreSQLOperationalItemRepository,
    PostgreSQLOrganizationEventRepository,
    PostgreSQLGovernanceRepository,
    PostgreSQLCalendarRepository,
)

from engines.communication.infrastructure.repositories import (
    PostgreSQLCommunicationRepository,
)

from infrastructure.database.meeting_repository import (
    PostgreSQLMeetingRepository,
)

from application.meetings import (
    MeetingTranscriptService,
    MeetingIntelligenceService,
)

from domain.reminders.services import (
    ReminderService,
)

from infrastructure.meetings.microsoft_teams_subscription_provider import (
    MicrosoftTeamsSubscriptionProvider,
)

from application.meetings.teams_subscription_service import (
    TeamsSubscriptionService,
)

from infrastructure.config.settings import get_settings

from infrastructure.database import (
    PostgreSQLMeetingTranscriptRepository,
    PostgreSQLTeamsSubscriptionRepository,
    PostgreSQLReminderRepository,
)

from domain.observation import (
    KnowledgeObservationRule,
    OperationalObservationRule,
    OrganizationalIntentObservationRule,
    QuestionObservationRule,
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
)

from domain.organization import (
    KnowledgeOrganizationRule,
    OperationalOrganizationRule,
    OrganizationalIntentOrganizationRule,
    QuestionOrganizationRule,
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
)

from domain.reasoning import (
    SimpleReasoningService,
)
from domain.reasoning.rankers import (
    KeywordRanker,
)
from engines.knowledge.infrastructure.indexing import (
    NullKnowledgeIndexer,
)

from infrastructure.meetings.microsoft_graph_token_provider import (
    MicrosoftGraphTokenProvider,
)

from infrastructure.meetings.microsoft_teams_transcript_provider import (
    MicrosoftTeamsTranscriptProvider,
)

from infrastructure.meetings.microsoft_teams_recording_provider import (
    MicrosoftTeamsRecordingProvider,
)
from infrastructure.llm import (
    OpenRouterClient,
    LocalEmbeddingClient,
)

from application.knowledge_base import (
    KnowledgeBaseIngestionService,
    KnowledgeBaseRetrievalService,
    KnowledgeBaseAnswerService,
)

from infrastructure.database import (
    PostgreSQLKnowledgeBaseDocumentRepository,
    PostgreSQLKnowledgeBaseChunkRepository,
)

from infrastructure.documents import (
    DocumentParser,
    DocumentChunker,
)

from domain.calendar.value_objects import (
    CalendarReminderPolicy,
)

from application.calendar import (
    AudienceResolutionService,
    SlackMembershipDirectoryProvider,
    CalendarService,
    CalendarAgent,
    CalendarReminderWorker,
)

from engines.slack.services.slack_identity_service import (
    SlackIdentityService,
)

from engines.slack.services.slack_client import (
    SlackClient,
)

def bootstrap(
) -> ApplicationContainer:
    """
    Assemble the complete POLIS
    application.
    """
    settings = get_settings()
    repository = PostgreSQLKnowledgeRepository()
    communication_repository = PostgreSQLCommunicationRepository()
    activity_repository = PostgreSQLActivityRepository()
    meeting_transcript_repository = (
        PostgreSQLMeetingTranscriptRepository()
    )
    meeting_repository = PostgreSQLMeetingRepository()
    teams_subscription_repository = (
        PostgreSQLTeamsSubscriptionRepository()
    )
    reminder_repository = PostgreSQLReminderRepository()
    operational_item_repository = PostgreSQLOperationalItemRepository()
    organization_event_repository = (
        PostgreSQLOrganizationEventRepository()
    )
    operational_item_service = OperationalItemService(
        operational_item_repository,
    )

    microsoft_graph_token_provider = (
        MicrosoftGraphTokenProvider()
    )

    microsoft_teams_transcript_provider = (
        MicrosoftTeamsTranscriptProvider(
            microsoft_graph_token_provider,
        )
    )

    microsoft_teams_recording_provider = (
        MicrosoftTeamsRecordingProvider(
            microsoft_graph_token_provider,
        )
    )

    microsoft_teams_subscription_provider = (
        MicrosoftTeamsSubscriptionProvider(
            microsoft_graph_token_provider,
        )
    )
    teams_subscription_service = TeamsSubscriptionService(
        repository=teams_subscription_repository,
        provider=microsoft_teams_subscription_provider,
        notification_url=settings.teams_webhook_url,
    )
    teams_recording_subscription_service = TeamsSubscriptionService(
        repository=teams_subscription_repository,
        provider=microsoft_teams_subscription_provider,
        notification_url=settings.teams_webhook_url,
        resource=TeamsSubscriptionService.RECORDING_RESOURCE,
    )

    reminder_service = ReminderService(
        repository=reminder_repository,
    )
    meeting_transcript_service = MeetingTranscriptService(
        repository=meeting_transcript_repository,
        meeting_repository=meeting_repository,
    )
    attendance_calculator = AttendanceCalculator()

    activity_service = ActivityService(
        activity_repository,
        attendance_calculator,
    )

    activity_detector = ActivityDetector()

    activity_processor = ActivityProcessor(
	    detector=activity_detector,
	    activity_service=activity_service,
	)
    activity_question_service = ActivityQuestionService(
        activity_service=activity_service,
    )
    indexer = NullKnowledgeIndexer()

    validator = SimpleKnowledgeValidator(
        repository=repository,
        indexer=indexer,
    )

    knowledge_acceptance_service = KnowledgeAcceptanceService(
        repository=repository,
    )

    llm_client = OpenRouterClient()
    meeting_intelligence_service = MeetingIntelligenceService(
        transcript_repository=meeting_transcript_repository,
        llm_client=llm_client,
        organization_event_repository=organization_event_repository,
    )

    knowledge_base_vector_repository = (
        QdrantKnowledgeBaseRepository()
    )

    knowledge_base_embedding_client = (
        LocalEmbeddingClient()
    )

    knowledge_base_retrieval = (
        KnowledgeBaseRetrievalService(
            vector_repository=knowledge_base_vector_repository,
            embedding_client=knowledge_base_embedding_client,
        )
    )

    knowledge_base_ingestion = (
        KnowledgeBaseIngestionService(
            document_repository=(
                PostgreSQLKnowledgeBaseDocumentRepository()
            ),
            chunk_repository=(
                PostgreSQLKnowledgeBaseChunkRepository()
            ),
            vector_repository=(
                knowledge_base_vector_repository
            ),
            object_storage=(
                MinIOKnowledgeBaseStorage()
            ),
            parser=DocumentParser(),
            chunker=DocumentChunker(),
            embedding_client=(
                knowledge_base_embedding_client
            ),
        )
    )

    knowledge_base_answer = KnowledgeBaseAnswerService(
        llm_client=llm_client,
    )

    knowledge_understanding = (
        LLMKnowledgeUnderstanding(
            llm_client,
        )
    )
    operational_understanding = (
        LLMOperationalUnderstanding(
            llm_client,
        )
    )
    organizational_intent_understanding = (
        LLMOrganizationalIntentUnderstanding(
            llm_client,
        )
    )
    observation_registry = ObservationRuleRegistry()

    observation_registry.register(
        KnowledgeObservationRule(
            knowledge_understanding,
        ),
    )
    observation_registry.register(
        QuestionObservationRule(),
    )
    observation_registry.register(
        OperationalObservationRule(
            operational_understanding,
        ),
    )
    observation_registry.register(
        OrganizationalIntentObservationRule(
            organizational_intent_understanding,
        ),
    )
    observation_extractor = (
        RuleBasedObservationExtractor(
            observation_registry,
        )
    )
    organization_registry = (
        OrganizationEventRuleRegistry()
    )

    organization_registry.register(
        KnowledgeOrganizationRule(),
    )
    organization_registry.register(
        QuestionOrganizationRule(),
    )
    organization_registry.register(
        OperationalOrganizationRule(),
    )
    organization_registry.register(
        OrganizationalIntentOrganizationRule(),
    )

    organization_builder = (
        RuleBasedOrganizationEventBuilder(
            organization_registry,
        )
    )
    knowledge_registry = KnowledgeRuleRegistry()

    knowledge_registry.register(
        KnowledgeDiscoveryRule(),
    )

    knowledge_builder = (
        RuleBasedKnowledgeBuilder(
            knowledge_registry,
        )
    )
    
    reasoning = SimpleReasoningService(
        repository,
        communication_repository=communication_repository,
        llm_client=llm_client,
        ranker=KeywordRanker(),
    )

    knowledge_agent = KnowledgeAgent(
        knowledge_repository=repository,
        retrieval_service=knowledge_base_retrieval,
        answer_service=knowledge_base_answer,
        llm_client=llm_client,
        organization_event_repository=organization_event_repository,
    )

    operations_agent = OperationsAgent(
        repository=operational_item_repository,
        operational_item_service=operational_item_service,
        reminder_service=reminder_service,
    )

    governance_repository = PostgreSQLGovernanceRepository()
    governance_agent = GovernanceAgent(
        repository=governance_repository,
        operations_agent=operations_agent,
        knowledge_agent=knowledge_agent,
        organization_event_repository=organization_event_repository,
        enabled=settings.enable_governance_engine,
    )

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=observation_extractor,
        organization_builder=organization_builder,
        knowledge_builder=knowledge_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=knowledge_acceptance_service,
        reasoning_service=reasoning,
        operational_item_service=operational_item_service,
        organization_event_repository=organization_event_repository,
        knowledge_agent=knowledge_agent,
        operations_agent=operations_agent,
        governance_agent=governance_agent,
    )

    calendar_repository = PostgreSQLCalendarRepository()
    slack_identity_service = SlackIdentityService()
    membership_provider = SlackMembershipDirectoryProvider(
        slack_identity_service=slack_identity_service,
    )
    audience_service = AudienceResolutionService(
        directory_provider=membership_provider,
        organization_channel_id=settings.calendar_organization_channel,
    )
    calendar_reminder_policy = CalendarReminderPolicy(
        offset_hours=settings.calendar_reminder_offset_hours,
    )
    calendar_service = CalendarService(
        repository=calendar_repository,
        audience_service=audience_service,
        reminder_policy=calendar_reminder_policy,
        default_timezone=settings.calendar_default_timezone,
    )
    calendar_agent = CalendarAgent(
        service=calendar_service,
        default_timezone=settings.calendar_default_timezone,
        identity_resolver=slack_identity_service,
    )
    calendar_slack_client = SlackClient()
    calendar_worker = CalendarReminderWorker(
        repository=calendar_repository,
        slack_client=calendar_slack_client,
        poll_interval_seconds=settings.calendar_worker_poll_interval_seconds,
        max_attempts=settings.calendar_max_retry_attempts,
    )

    engine = SimpleCognitiveEngine(
        pipeline,
        reasoning,
        activity_question_service,
        operational_item_service=operational_item_service,
        knowledge_base_retrieval_service=knowledge_base_retrieval,
        knowledge_base_answer_service=knowledge_base_answer,
        knowledge_agent=knowledge_agent,
        operations_agent=operations_agent,
        governance_agent=governance_agent,
        meeting_intelligence_service=meeting_intelligence_service,
        calendar_agent=calendar_agent,
    )
    return ApplicationContainer(
        engine=engine,
        repository=repository,
        activity_service=activity_service,
        activity_processor=activity_processor,
        activity_question_service=activity_question_service,
        meeting_transcript_service=meeting_transcript_service,
        meeting_intelligence_service=meeting_intelligence_service,
        meeting_transcript_provider=microsoft_teams_transcript_provider,
        meeting_recording_provider=microsoft_teams_recording_provider,
        teams_subscription_repository=teams_subscription_repository,
        teams_subscription_service=teams_subscription_service,
        teams_recording_subscription_service=(
            teams_recording_subscription_service
        ),
        reminder_repository=reminder_repository,
        reminder_service=reminder_service,
        knowledge_base_ingestion_service=knowledge_base_ingestion,
        knowledge_agent=knowledge_agent,
        operations_agent=operations_agent,
        governance_agent=governance_agent,
        calendar_repository=calendar_repository,
        calendar_service=calendar_service,
        calendar_agent=calendar_agent,
        calendar_worker=calendar_worker,
    )



