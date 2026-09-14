from datetime import datetime, timezone

import pytest

from domain.meetings import Meeting


def test_meeting_create_generates_identity():
    started_at = datetime.now(timezone.utc)

    meeting = Meeting.create(
        external_id="teams-001",
        title="Weekly Planning",
        source="Microsoft Teams",
        started_at=started_at,
    )

    assert meeting.graph_id is not None
    assert meeting.external_id == "teams-001"
    assert meeting.title == "Weekly Planning"
    assert meeting.source == "Microsoft Teams"
    assert meeting.started_at == started_at


def test_meeting_create_preserves_metadata():
    metadata = {
        "team_id": "team-001",
        "organizer_id": "user-001",
    }

    meeting = Meeting.create(
        external_id="teams-002",
        title="Project Review",
        source="Microsoft Teams",
        started_at=datetime.now(timezone.utc),
        metadata=metadata,
    )

    assert meeting.metadata == metadata


def test_meeting_rejects_empty_external_id():
    with pytest.raises(ValueError, match="external_id must not be empty"):
        Meeting.create(
            external_id="",
            title="Test Meeting",
            source="Microsoft Teams",
            started_at=datetime.now(timezone.utc),
        )


def test_meeting_rejects_empty_title():
    with pytest.raises(ValueError, match="title must not be empty"):
        Meeting.create(
            external_id="teams-003",
            title="",
            source="Microsoft Teams",
            started_at=datetime.now(timezone.utc),
        )


def test_meeting_rejects_empty_source():
    with pytest.raises(ValueError, match="source must not be empty"):
        Meeting.create(
            external_id="teams-004",
            title="Test Meeting",
            source="",
            started_at=datetime.now(timezone.utc),
        )