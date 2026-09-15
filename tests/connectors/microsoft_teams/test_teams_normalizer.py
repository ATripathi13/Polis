from datetime import timedelta

from connectors.microsoft_teams.models import (
    TeamsTranscriptSegment,
)
from connectors.microsoft_teams.normalizers import (
    TeamsNormalizer,
)
from engines.communication.domain.enums import (
    EventSource,
)


def test_teams_normalizer_creates_communication_event():
    segment = TeamsTranscriptSegment(
        speaker="Test Speaker",
        text="We should launch this Monday.",
        start=timedelta(seconds=4),
        end=timedelta(seconds=8.25),
    )

    event = TeamsNormalizer().normalize(
        segment=segment,
        meeting_id="meeting-123",
        transcript_id="transcript-456",
    )

    assert event.source == EventSource.MICROSOFT_TEAMS

    assert event.source_event_id == (
        "transcript-456:4.000:8.250:Test Speaker"
    )

    assert event.actor.display_name == "Test Speaker"
    assert (
        event.actor.identity.external_ids["microsoft_teams"]
        == "Test Speaker"
    )

    assert event.channel.name == "meeting-123"
    assert event.channel.channel_type == "meeting"

    assert event.content.body == (
        "We should launch this Monday."
    )

    assert event.content.metadata["meeting_id"] == "meeting-123"
    assert event.content.metadata["transcript_id"] == "transcript-456"
    assert event.content.metadata["speaker"] == "Test Speaker"
    assert event.content.metadata["start_seconds"] == 4.0
    assert event.content.metadata["end_seconds"] == 8.25


def test_teams_normalizer_preserves_meeting_correlation():
    segment = TeamsTranscriptSegment(
        speaker="Another Speaker",
        text="Hello.",
        start=timedelta(seconds=1),
        end=timedelta(seconds=2),
    )

    event = TeamsNormalizer().normalize(
        segment=segment,
        meeting_id="meeting-789",
        transcript_id="transcript-abc",
    )

    assert event.correlation_id.business_id == "meeting-789"
