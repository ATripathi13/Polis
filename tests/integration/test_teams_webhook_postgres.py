from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi.testclient import TestClient

from api.dependencies import (
    get_meeting_transcript_provider,
    get_teams_service,
)
from api.app import app
from application.meetings import MeetingTranscriptInput
from application.pipeline.pipeline import PolisPipeline
from connectors.microsoft_teams.normalizers import TeamsNormalizer
from connectors.microsoft_teams.services import TeamsService
from domain.common.identifier import Identifier
from domain.events import EventDispatcher, EventRegistry
from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeDiscoveryRule,
    KnowledgeRuleRegistry,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)
from domain.observation import (
    ObservationRuleRegistry,
    OperationalObservationRule,
    RuleBasedObservationExtractor,
)
from domain.organization import (
    OrganizationEventRuleRegistry,
    OperationalOrganizationRule,
    RuleBasedOrganizationEventBuilder,
)
from engines.communication.application.services import CommunicationService
from engines.communication.infrastructure.repositories import (
    PostgreSQLCommunicationRepository,
)
from engines.knowledge.infrastructure.indexing import NullKnowledgeIndexer
from infrastructure.database import (
    PostgreSQLOrganizationEventRepository,
    SessionLocal,
)
from infrastructure.database.models import (
    CommunicationEventModel,
    MeetingModel,
    MeetingTranscriptModel,
    OrganizationEventModel,
)


class FakeTranscriptProvider:
    def __init__(self, transcript: MeetingTranscriptInput):
        self.transcript = transcript

    def get_transcript_by_notification(
        self,
        *,
        user_id: str,
        online_meeting_id: str,
        transcript_id: str,
    ) -> MeetingTranscriptInput:
        assert online_meeting_id == self.transcript.meeting_id
        assert transcript_id == self.transcript.metadata["transcript_id"]
        return self.transcript


class FakeOperationalUnderstanding:
    def analyze(self, text: str) -> dict:
        if "migrate" in text.lower():
            return {
                "is_operational": True,
                "type": "task",
                "summary": "Migrate database to production",
                "confidence": 0.95,
                "status": "completed",
            }
        return {"is_operational": False}


class NoKnowledgeCandidates:
    def build(self, event):
        return []


class RecordingEngine:
    def __init__(self, pipeline: PolisPipeline):
        self.pipeline = pipeline
        self.calls = 0

    def learn(self, communication) -> None:
        self.calls += 1
        self.pipeline.process(communication)


def test_teams_webhook_persists_transcript_communications_and_events():
    suffix = str(uuid4())
    meeting_id = str(uuid4())
    transcript_id = f"teams-transcript-{suffix}"
    captured_at = datetime.now(timezone.utc)
    transcript_text = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:03.000\n"
        "<v Alice>Task completed: migrate database to production.</v>\n"
    )

    transcript = MeetingTranscriptInput(
        meeting_id=meeting_id,
        transcript=transcript_text,
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice"],
        metadata={
            "transcript_id": transcript_id,
            "meeting_started_at": captured_at.isoformat(),
        },
    )
    provider = FakeTranscriptProvider(transcript)

    observation_registry = ObservationRuleRegistry()
    observation_registry.register(
        OperationalObservationRule(FakeOperationalUnderstanding())
    )
    observation_extractor = RuleBasedObservationExtractor(
        observation_registry
    )

    organization_registry = OrganizationEventRuleRegistry()
    organization_registry.register(OperationalOrganizationRule())
    organization_builder = RuleBasedOrganizationEventBuilder(
        organization_registry
    )

    knowledge_repository = InMemoryKnowledgeRepository()
    knowledge_registry = KnowledgeRuleRegistry()
    knowledge_registry.register(KnowledgeDiscoveryRule())
    knowledge_builder = RuleBasedKnowledgeBuilder(knowledge_registry)
    validator = SimpleKnowledgeValidator(
        knowledge_repository,
        NullKnowledgeIndexer(),
    )

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=observation_extractor,
        organization_builder=organization_builder,
        knowledge_builder=NoKnowledgeCandidates(),
        knowledge_validator=validator,
        knowledge_acceptance_service=None,
        reasoning_service=None,
        operational_item_service=None,
        organization_event_repository=PostgreSQLOrganizationEventRepository(),
    )

    engine = RecordingEngine(pipeline)
    teams_service = TeamsService(
        normalizer=TeamsNormalizer(),
        communication_service=CommunicationService(
            repository=PostgreSQLCommunicationRepository(),
            dispatcher=EventDispatcher(EventRegistry()),
        ),
        cognitive_engine=engine,
    )

    dependencies = (
        get_meeting_transcript_provider,
        get_teams_service,
    )
    previous_overrides = {
        dependency: app.dependency_overrides.get(dependency)
        for dependency in dependencies
    }
    had_previous_override = {
        dependency: dependency in app.dependency_overrides
        for dependency in dependencies
    }

    transcript_graph_id = str(
        uuid5(NAMESPACE_URL, f"microsoft-teams:transcript:{transcript_id}")
    )

    try:
        app.dependency_overrides[get_meeting_transcript_provider] = (
            lambda: provider
        )
        app.dependency_overrides[get_teams_service] = (
            lambda: teams_service
        )

        client = TestClient(app)
        payload = {
            "value": [
                {
                    "clientState": "polis-teams-transcript",
                    "resource": (
                        f"users('test-user')/onlineMeetings('{meeting_id}')"
                        f"/transcripts('{transcript_id}')"
                    ),
                    "resourceData": {"id": transcript_id},
                }
            ]
        }

        first_response = client.post("/teams/webhook", json=payload)
        assert first_response.status_code == 200, first_response.text
        assert first_response.json() == {"status": "accepted"}

        with SessionLocal() as session:
            saved_transcript = session.get(
                MeetingTranscriptModel,
                transcript_graph_id,
            )
            assert saved_transcript is not None
            assert saved_transcript.transcript == transcript_text

            communications = (
                session.query(CommunicationEventModel)
                .filter(
                    CommunicationEventModel.source == "microsoft_teams",
                    CommunicationEventModel.source_event_id.like(
                        f"{transcript_id}:%"
                    ),
                )
                .all()
            )
            assert len(communications) == 1

            organization_events = (
                session.query(OrganizationEventModel)
                .filter(
                    OrganizationEventModel.source_type == "microsoft_teams",
                    OrganizationEventModel.correlation_business_id
                    == meeting_id,
                )
                .all()
            )
            assert len(organization_events) == 1
            assert organization_events[0].event_type == "task_completed"
            assert (
                organization_events[0].summary
                == "Migrate database to production"
            )

        second_response = client.post("/teams/webhook", json=payload)
        assert second_response.status_code == 200, second_response.text
        assert second_response.json() == {"status": "accepted"}

        assert engine.calls == 2

        with SessionLocal() as session:
            communications_after_replay = (
                session.query(CommunicationEventModel)
                .filter(
                    CommunicationEventModel.source == "microsoft_teams",
                    CommunicationEventModel.source_event_id.like(
                        f"{transcript_id}:%"
                    ),
                )
                .count()
            )
            events_after_replay = (
                session.query(OrganizationEventModel)
                .filter(
                    OrganizationEventModel.source_type == "microsoft_teams",
                    OrganizationEventModel.correlation_business_id
                    == meeting_id,
                )
                .count()
            )
            transcripts_after_replay = (
                session.query(MeetingTranscriptModel)
                .filter(
                    MeetingTranscriptModel.id == transcript_graph_id
                )
                .count()
            )

        assert communications_after_replay == 1
        assert events_after_replay == 1
        assert transcripts_after_replay == 1

    finally:
        for dependency in dependencies:
            if had_previous_override[dependency]:
                app.dependency_overrides[dependency] = (
                    previous_overrides[dependency]
                )
            else:
                app.dependency_overrides.pop(dependency, None)

        with SessionLocal() as session:
            session.query(OrganizationEventModel).filter(
                OrganizationEventModel.source_type == "microsoft_teams",
                OrganizationEventModel.correlation_business_id == meeting_id,
            ).delete(synchronize_session=False)

            session.query(CommunicationEventModel).filter(
                CommunicationEventModel.source == "microsoft_teams",
                CommunicationEventModel.source_event_id.like(
                    f"{transcript_id}:%"
                ),
            ).delete(synchronize_session=False)

            session.query(MeetingTranscriptModel).filter(
                MeetingTranscriptModel.id == transcript_graph_id
            ).delete(synchronize_session=False)

            session.query(MeetingModel).filter(
                MeetingModel.external_id == meeting_id
            ).delete(synchronize_session=False)

            session.commit()
