
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_meeting_intelligence_service
from application.meetings import MeetingIntelligenceService
from domain.common.identifier import Identifier
from domain.meetings import MeetingTranscript
from domain.observation import Observation, ObservationType
from domain.organization import OrganizationEvent, OrganizationEventType
from infrastructure.database.connection import SessionLocal
from infrastructure.database.meeting_transcript_repository import (
    PostgreSQLMeetingTranscriptRepository,
)
from infrastructure.database.models import (
    MeetingTranscriptModel,
    OrganizationEventModel,
)
from infrastructure.database.organization_event_repository import (
    PostgreSQLOrganizationEventRepository,
)


class RecordingStructuredLLM:
    def __init__(self):
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return """
{
  "summary": "The team completed the database migration task.",
  "topics": ["Database migration"],
  "decisions": ["Proceed with the production migration"],
  "action_items": ["Verify the production migration"],
  "risks": [],
  "open_questions": [],
  "confidence": 0.94
}
""".strip()


def test_persisted_meeting_transcript_and_event_reach_intelligence_api():
    meeting_id = str(uuid4())
    transcript_id = f"teams-transcript-{uuid4()}"
    transcript_graph_id = uuid4()
    event_source_id = f"teams-source-{uuid4()}"
    captured_at = datetime.now(timezone.utc)

    transcript_repository = PostgreSQLMeetingTranscriptRepository()
    event_repository = PostgreSQLOrganizationEventRepository()
    llm = RecordingStructuredLLM()

    transcript = MeetingTranscript(
        identifier=Identifier(
            graph_id=transcript_graph_id,
            business_id=transcript_id,
        ),
        meeting_id=meeting_id,
        transcript=(
            "Alice: The database migration is complete. "
            "Bob: We will verify the production migration."
        ),
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice", "Bob"],
        metadata={"transcript_id": transcript_id},
    )

    event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_COMPLETED,
        summary="Database migration completed",
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary="Database migration completed",
                confidence=0.95,
                evidence=[transcript_id],
                correlation_id=Identifier(business_id=meeting_id),
                occurred_at=captured_at,
            )
        ],
        confidence=0.95,
        correlation_id=Identifier(business_id=meeting_id),
        occurred_at=captured_at,
    )

    dependency = get_meeting_intelligence_service
    had_previous_override = dependency in app.dependency_overrides
    previous_override = app.dependency_overrides.get(dependency)

    try:
        transcript_repository.save(transcript)
        event_repository.save(
            event,
            source_type="microsoft_teams",
            source_event_id=event_source_id,
            correlation_id=meeting_id,
        )

        # Verify that both records can be read back from PostgreSQL.
        persisted_transcripts = transcript_repository.find_by_meeting_id(
            meeting_id
        )
        assert len(persisted_transcripts) == 1
        assert persisted_transcripts[0].transcript == transcript.transcript
        assert (
            persisted_transcripts[0].metadata["transcript_id"]
            == transcript_id
        )

        persisted_events = event_repository.find_by_correlation(meeting_id)
        assert len(persisted_events) == 1
        assert persisted_events[0].summary == "Database migration completed"
        assert persisted_events[0].observations[0].evidence == [transcript_id]

        service = MeetingIntelligenceService(
            transcript_repository=transcript_repository,
            llm_client=llm,
            organization_event_repository=event_repository,
        )

        app.dependency_overrides[get_meeting_intelligence_service] = (
            lambda: service
        )

        response = TestClient(app).get(
            f"/meetings/{meeting_id}/intelligence"
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"] == (
            "The team completed the database migration task."
        )
        assert payload["decisions"] == [
            "Proceed with the production migration"
        ]
        assert payload["action_items"] == [
            "Verify the production migration"
        ]
        assert payload["confidence"] == 0.94
        assert transcript.transcript in llm.prompt
        assert (
            "task_completed: Database migration completed"
            in llm.prompt
        )
        assert "None recorded." not in llm.prompt

    finally:
        if had_previous_override:
            app.dependency_overrides[dependency] = previous_override
        else:
            app.dependency_overrides.pop(dependency, None)

        with SessionLocal() as session:
            event_record = (
                session.query(OrganizationEventModel)
                .filter_by(
                    source_type="microsoft_teams",
                    source_event_id=event_source_id,
                )
                .one_or_none()
            )
            if event_record is not None:
                session.delete(event_record)

            transcript_record = session.get(
                MeetingTranscriptModel,
                str(transcript_graph_id),
            )
            if transcript_record is not None:
                session.delete(transcript_record)

            session.commit()


class RecordingSummaryLLM:
    def __init__(self):
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return "The team completed the migration and agreed to verify production."


def test_persisted_meeting_transcript_reaches_summary_api():
    meeting_id = str(uuid4())
    transcript_id = f"summary-transcript-{uuid4()}"
    transcript_graph_id = uuid4()
    transcript_text = (
        "Alice: The database migration is complete. "
        "Bob: We agreed to verify the production migration."
    )
    captured_at = datetime.now(timezone.utc)

    transcript_repository = PostgreSQLMeetingTranscriptRepository()
    llm = RecordingSummaryLLM()
    transcript = MeetingTranscript(
        identifier=Identifier(
            graph_id=transcript_graph_id,
            business_id=transcript_id,
        ),
        meeting_id=meeting_id,
        transcript=transcript_text,
        source="Microsoft Teams",
        captured_at=captured_at,
        participants=["Alice", "Bob"],
        metadata={"transcript_id": transcript_id},
    )

    dependency = get_meeting_intelligence_service
    had_previous_override = dependency in app.dependency_overrides
    previous_override = app.dependency_overrides.get(dependency)

    try:
        transcript_repository.save(transcript)

        service = MeetingIntelligenceService(
            transcript_repository=transcript_repository,
            llm_client=llm,
        )
        app.dependency_overrides[dependency] = lambda: service

        response = TestClient(app).get(
            f"/meetings/{meeting_id}/summary"
        )

        assert response.status_code == 200
        assert response.json() == {
            "answer": (
                "The team completed the migration and agreed to verify production."
            )
        }
        assert meeting_id in llm.prompt
        assert transcript_text in llm.prompt

    finally:
        if had_previous_override:
            app.dependency_overrides[dependency] = previous_override
        else:
            app.dependency_overrides.pop(dependency, None)

        with SessionLocal() as session:
            transcript_record = session.get(
                MeetingTranscriptModel,
                str(transcript_graph_id),
            )
            if transcript_record is not None:
                session.delete(transcript_record)
            session.commit()
