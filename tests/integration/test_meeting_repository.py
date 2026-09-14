from datetime import datetime, timezone
from uuid import uuid4

from domain.meetings import Meeting
from infrastructure.database.meeting_repository import PostgreSQLMeetingRepository
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import MeetingModel


def test_meeting_repository_save_and_find():
    repository = PostgreSQLMeetingRepository()

    meeting = Meeting.create(
        external_id=f"teams-test-{uuid4()}",
        title="Repository Integration Test",
        source="Microsoft Teams",
        started_at=datetime.now(timezone.utc),
        metadata={"test": True},
    )

    repository.save(meeting)

    try:
        found = repository.find(str(meeting.graph_id))

        assert found is not None
        assert found.graph_id == meeting.graph_id
        assert found.external_id == meeting.external_id
        assert found.title == meeting.title
        assert found.source == meeting.source
        assert found.started_at == meeting.started_at
        assert found.metadata == meeting.metadata

    finally:
        with SessionLocal() as session:
            record = session.get(
                MeetingModel,
                str(meeting.graph_id),
            )

            if record is not None:
                session.delete(record)
                session.commit()


def test_meeting_repository_find_by_external_id():
    repository = PostgreSQLMeetingRepository()

    meeting = Meeting.create(
        external_id=f"teams-external-{uuid4()}",
        title="External ID Test",
        source="Microsoft Teams",
        started_at=datetime.now(timezone.utc),
    )

    repository.save(meeting)

    try:
        found = repository.find_by_external_id(
            meeting.external_id
        )

        assert found is not None
        assert found.graph_id == meeting.graph_id
        assert found.external_id == meeting.external_id
        assert found.title == meeting.title

    finally:
        with SessionLocal() as session:
            record = session.get(
                MeetingModel,
                str(meeting.graph_id),
            )

            if record is not None:
                session.delete(record)
                session.commit()