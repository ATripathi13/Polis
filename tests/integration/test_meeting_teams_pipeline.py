"""
Integration tests for Microsoft Teams transcript ingestion into
the Organizational Event Engine and Meeting Intelligence Service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from domain.common.identifier import Identifier
from domain.meetings import MeetingTranscript
from domain.observation import (
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
    OperationalObservationRule,
)
from domain.organization import (
    InMemoryOrganizationEventRepository,
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
    OperationalOrganizationRule as OrgOperationalRule,
    OrganizationEventType,
)
from domain.operations import OperationalItemStatus, OperationalItemType
from application.operations import OperationalItemService
from application.pipeline.pipeline import PolisPipeline
from application.cognitive import SimpleCognitiveEngine
from application.meetings import MeetingIntelligenceService
from connectors.microsoft_teams.normalizers import TeamsNormalizer
from connectors.microsoft_teams.models import TeamsTranscriptSegment
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.application.services import CommunicationService
from engines.communication.application.commands import IngestCommunicationCommand
from engines.communication.infrastructure.repositories import InMemoryCommunicationRepository
from domain.events import EventDispatcher, EventRegistry
from engines.knowledge.infrastructure.indexing import NullKnowledgeIndexer
from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeDiscoveryRule,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)
from application.services.knowledge_acceptance_service import (
    KnowledgeAcceptanceService,
)


class FakeTranscriptRepo:
    def __init__(self, transcripts):
        self.transcripts = transcripts

    def find_by_meeting_id(self, meeting_id):
        return [t for t in self.transcripts if t.meeting_id == meeting_id]


class FakeOperationalRepo:
    def __init__(self):
        self.items = []

    def save(self, item):
        for idx, existing in enumerate(self.items):
            if existing.identifier == item.identifier:
                self.items[idx] = item
                return item
        self.items.append(item)
        return item

    def find_by_source_event(self, source_type, source_event_id, item_type):
        for item in self.items:
            if (
                item.source_type == source_type
                and item.source_event_id == source_event_id
                and item.item_type == item_type
            ):
                return item
        return None


class FakeOperationalUnderstanding:
    def analyze(self, text):
        if "migrate" in text.lower():
            return {
                "is_operational": True,
                "type": "task",
                "summary": "Migrate database to production",
                "confidence": 0.95,
                "status": "completed",
            }
        return {"is_operational": False}


class RecordingStructuredLLM:
    def __init__(self):
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return """
{
  "summary": "Team agreed to finalize the database migration.",
  "topics": ["Database migration"],
  "decisions": ["Proceed with production migration"],
  "action_items": ["Migrate database to production"],
  "risks": [],
  "open_questions": [],
  "confidence": 0.94
}
""".strip()


def test_teams_ingestion_end_to_end_to_organization_events_and_meeting_intelligence():
    meeting_id = "online-meeting-teams-777"
    transcript_id = "transcript-vtt-888"

    # 1. Setup Organizational Event Engine Pipeline
    obs_registry = ObservationRuleRegistry()
    obs_registry.register(
        OperationalObservationRule(FakeOperationalUnderstanding())
    )
    obs_extractor = RuleBasedObservationExtractor(obs_registry)

    org_registry = OrganizationEventRuleRegistry()
    org_registry.register(OrgOperationalRule())
    org_builder = RuleBasedOrganizationEventBuilder(org_registry)

    knowledge_repo = InMemoryKnowledgeRepository()
    knowledge_acceptance = KnowledgeAcceptanceService(knowledge_repo)
    validator = SimpleKnowledgeValidator(knowledge_repo, NullKnowledgeIndexer())
    knowledge_registry = KnowledgeRuleRegistry()
    knowledge_registry.register(KnowledgeDiscoveryRule())
    knowledge_builder = RuleBasedKnowledgeBuilder(knowledge_registry)

    op_repo = FakeOperationalRepo()
    op_service = OperationalItemService(op_repo)

    org_event_repo = InMemoryOrganizationEventRepository()

    # Pre-populate an unrelated event from another meeting
    normalizer = TeamsNormalizer()
    other_meeting_id = "other-meeting-999"
    other_comm = normalizer.normalize(
        segment=TeamsTranscriptSegment(
            speaker="Bob",
            text="Migrate an unrelated database in another meeting",
            start=datetime.now(timezone.utc) - datetime.now(timezone.utc),
            end=datetime.now(timezone.utc) - datetime.now(timezone.utc),
        ),
        meeting_id=other_meeting_id,
        transcript_id="other-transcript",
    )
    other_obs = obs_extractor.extract(other_comm)
    if other_obs:
        other_events = org_builder.build(other_obs)
        for oe in other_events:
            org_event_repo.save(
                oe,
                source_type="microsoft_teams",
                source_event_id="other-transcript:0.0:1.0:Bob",
                correlation_id=other_comm.correlation_id,
            )

    assert other_obs, "Test setup must create an unrelated operational observation"
    assert org_event_repo.find_by_correlation(other_meeting_id), "Test setup must persist an unrelated meeting event"

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=obs_extractor,
        organization_builder=org_builder,
        knowledge_builder=knowledge_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=knowledge_acceptance,
        reasoning_service=None,
        operational_item_service=op_service,
        organization_event_repository=org_event_repo,
    )

    # 2. Setup Meeting Intelligence and Cognitive Engine
    llm = RecordingStructuredLLM()

    # Stored transcript for the meeting
    raw_transcript_text = "Alice: We need to migrate database to production today."
    meeting_transcript = MeetingTranscript(
        identifier=Identifier(business_id=transcript_id),
        meeting_id=meeting_id,
        transcript=raw_transcript_text,
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
        metadata={"transcript_id": transcript_id},
    )
    transcript_repo = FakeTranscriptRepo([meeting_transcript])

    meeting_intelligence = MeetingIntelligenceService(
        transcript_repository=transcript_repo,
        llm_client=llm,
        organization_event_repository=org_event_repo,
    )

    engine = SimpleCognitiveEngine(
        pipeline=pipeline,
        question_answering=None,
        meeting_intelligence_service=meeting_intelligence,
    )

    # 3. Simulate Teams Ingestion Flow
    segment = TeamsTranscriptSegment(
        speaker="Alice",
        text="Task completed: migrate database to production",
        start=datetime.now(timezone.utc) - datetime.now(timezone.utc),
        end=datetime.now(timezone.utc) - datetime.now(timezone.utc),
    )
    normalizer = TeamsNormalizer()
    meeting_start_time = datetime(
        2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc
    )

    communication = normalizer.normalize(
        segment=segment,
        meeting_id=meeting_id,
        transcript_id=transcript_id,
        meeting_start_time=meeting_start_time,
    )

    assert communication.source == EventSource.MICROSOFT_TEAMS
    assert communication.correlation_id.business_id == meeting_id
    assert communication.source_event_id.startswith(transcript_id + ":")
    expected_occurred_at = meeting_start_time + segment.start
    expected_timestamp = f"{expected_occurred_at.timestamp():.6f}"

    assert (
        communication.content.metadata["source_timestamp"]
        == expected_timestamp
    )
    comm_repo = InMemoryCommunicationRepository()
    comm_service = CommunicationService(
        repository=comm_repo,
        dispatcher=EventDispatcher(EventRegistry()),
    )
    saved_comm = comm_service.process(IngestCommunicationCommand(event=communication))

    # Engine learns from communication segment
    engine.learn(saved_comm)

    # 4. Verify canonical event persistence and source provenance
    saved_events = org_event_repo.find_by_correlation(meeting_id)
    assert len(saved_events) == 1
    org_event = saved_events[0]
    assert org_event.event_type == OrganizationEventType.TASK_COMPLETED
    assert org_event.summary == "Migrate database to production"
    assert org_event.correlation_id.business_id == meeting_id

    # Downstream operational item was created with COMPLETED status
    assert len(op_repo.items) == 1
    assert op_repo.items[0].status == OperationalItemStatus.COMPLETED
    assert op_repo.items[0].source_type == "microsoft_teams"

    # 5. Verify Replay Idempotency
    engine.learn(saved_comm)
    assert len(org_event_repo.find_by_correlation(meeting_id)) == 1
    assert len(op_repo.items) == 1

    # 6. Verify Meeting Intelligence Enrichment
    # Now run meeting intelligence analysis through cognitive engine
    result = engine.analyze_meeting(meeting_id)

    assert result.summary == "Team agreed to finalize the database migration."
    assert result.decisions == ["Proceed with production migration"]
    assert result.action_items == ["Migrate database to production"]
    assert result.confidence == 0.94

    # Ensure canonical event from this meeting was injected into LLM prompt
    assert "task_completed: Migrate database to production" in llm.prompt
    assert raw_transcript_text in llm.prompt
    # Ensure unrelated events are not in the prompt
    assert other_meeting_id not in llm.prompt
