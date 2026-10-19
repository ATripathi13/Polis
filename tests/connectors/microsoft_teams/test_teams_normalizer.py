from datetime import datetime, timedelta, timezone

from connectors.microsoft_teams.models import (
    TeamsTranscriptSegment,
)
from connectors.microsoft_teams.normalizers import (
    TeamsNormalizer,
)
from domain.observation.rules.timestamp_utils import (
    resolve_occurred_at,
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
    assert "source_timestamp" not in event.content.metadata


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


def test_teams_normalizer_meeting_start_time_plus_segment_offset():
    normalizer = TeamsNormalizer()
    segment = TeamsTranscriptSegment(
        speaker="Alice",
        text="Starting the project update.",
        start=timedelta(seconds=42.5),
        end=timedelta(seconds=48.0),
    )

    # 1. Direct datetime meeting_start_time
    start_dt = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    event1 = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-100",
        transcript_id="transcript-100",
        meeting_start_time=start_dt,
    )
    expected_dt = datetime(2026, 10, 14, 10, 0, 42, 500000, tzinfo=timezone.utc)
    assert event1.content.metadata["source_timestamp"] == f"{expected_dt.timestamp():.6f}"
    assert resolve_occurred_at(event1) == expected_dt

    # 2. ISO string meeting_start_time
    event2 = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-100",
        transcript_id="transcript-100",
        meeting_start_time="2026-10-14T10:00:00Z",
    )
    assert event2.content.metadata["source_timestamp"] == f"{expected_dt.timestamp():.6f}"
    assert resolve_occurred_at(event2) == expected_dt

    # 3. Passed through metadata["meeting_started_at"] (Graph API standard)
    event3 = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-100",
        transcript_id="transcript-100",
        metadata={"meeting_started_at": "2026-10-14T10:00:00Z"},
    )
    assert event3.content.metadata["source_timestamp"] == f"{expected_dt.timestamp():.6f}"
    assert resolve_occurred_at(event3) == expected_dt

    # 4. Fallback to captured_at when meeting_start_time is absent
    capture_dt = datetime(2026, 10, 14, 11, 0, 0, tzinfo=timezone.utc)
    event4 = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-100",
        transcript_id="transcript-100",
        captured_at=capture_dt,
    )
    expected_capture_dt = datetime(2026, 10, 14, 11, 0, 42, 500000, tzinfo=timezone.utc)
    assert event4.content.metadata["source_timestamp"] == f"{expected_capture_dt.timestamp():.6f}"
    assert resolve_occurred_at(event4) == expected_capture_dt


def test_teams_normalizer_utc_normalization_and_timezone_handling():
    normalizer = TeamsNormalizer()
    segment = TeamsTranscriptSegment(
        speaker="Bob",
        text="Reviewing action items.",
        start=timedelta(seconds=10),
        end=timedelta(seconds=15),
    )

    # 1. Non-UTC timezone offset (+05:30)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_start = datetime(2026, 10, 14, 15, 30, 0, tzinfo=ist_tz)  # equivalent to 10:00:00 UTC
    event_ist = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-200",
        transcript_id="transcript-200",
        meeting_start_time=ist_start,
    )
    expected_utc = datetime(2026, 10, 14, 10, 0, 10, tzinfo=timezone.utc)
    resolved_ist = resolve_occurred_at(event_ist)
    assert resolved_ist == expected_utc
    assert resolved_ist.tzinfo == timezone.utc

    # 2. ISO string with non-UTC offset
    event_iso_offset = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-200",
        transcript_id="transcript-200",
        meeting_start_time="2026-10-14T15:30:00+05:30",
    )
    assert resolve_occurred_at(event_iso_offset) == expected_utc

    # 3. Naive datetime assumes UTC
    naive_start = datetime(2026, 10, 14, 10, 0, 0)
    event_naive = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-200",
        transcript_id="transcript-200",
        meeting_start_time=naive_start,
    )
    assert resolve_occurred_at(event_naive) == expected_utc

    # 4. Numeric epoch timestamp
    epoch_start = 1728900000.0  # 2024-10-14 10:00:00 UTC
    event_epoch = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-200",
        transcript_id="transcript-200",
        meeting_start_time=epoch_start,
    )
    expected_epoch_dt = datetime.fromtimestamp(epoch_start + 10.0, tz=timezone.utc)
    assert resolve_occurred_at(event_epoch) == expected_epoch_dt


def test_teams_normalizer_missing_timing_does_not_infer_offset():
    normalizer = TeamsNormalizer()
    segment = TeamsTranscriptSegment(
        speaker="Charlie",
        text="Relative time only segment.",
        start=timedelta(seconds=120),
        end=timedelta(seconds=130),
    )

    event = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-300",
        transcript_id="transcript-300",
    )

    # Relative offset must NOT be inferred as an absolute timestamp
    assert "source_timestamp" not in event.content.metadata
    assert resolve_occurred_at(event) == event.created_at


def test_teams_normalizer_existing_source_timestamp_preservation_and_resolution():
    normalizer = TeamsNormalizer()
    segment = TeamsTranscriptSegment(
        speaker="Dana",
        text="Explicit timestamp test.",
        start=timedelta(seconds=5),
        end=timedelta(seconds=10),
    )

    # 1. Explicit source_timestamp argument takes precedence
    event1 = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-400",
        transcript_id="transcript-400",
        meeting_start_time="2026-10-14T10:00:00Z",
        source_timestamp="1712345678.123456",
    )
    assert event1.content.metadata["source_timestamp"] == "1712345678.123456"
    assert resolve_occurred_at(event1) == datetime.fromtimestamp(1712345678.123456, tz=timezone.utc)

    # 2. Existing source_timestamp in metadata is preserved
    event2 = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-400",
        transcript_id="transcript-400",
        metadata={"source_timestamp": "1712345678.654321", "custom_key": "preserved"},
    )
    assert event2.content.metadata["source_timestamp"] == "1712345678.654321"
    assert event2.content.metadata["custom_key"] == "preserved"
    assert resolve_occurred_at(event2) == datetime.fromtimestamp(1712345678.654321, tz=timezone.utc)

    # 3. Invalid existing source_timestamp is preserved without raising, falling back to created_at
    event3 = normalizer.normalize(
        segment=segment,
        meeting_id="meeting-400",
        transcript_id="transcript-400",
        metadata={"source_timestamp": "not-a-timestamp"},
    )
    assert event3.content.metadata["source_timestamp"] == "not-a-timestamp"
    assert resolve_occurred_at(event3) == event3.created_at
