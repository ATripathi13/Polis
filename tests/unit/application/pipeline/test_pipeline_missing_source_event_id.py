"""
Regression tests for POLIS Gap 6: Missing Source Event ID Handling.
Covers deterministic fallback derivation, safe failure paths, duplicate suppression,
and unidentifiable event isolation in the execution pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from unittest.mock import MagicMock
import pytest
from sqlalchemy.exc import IntegrityError

from application.pipeline.pipeline import PolisPipeline
from domain.common.identifier import Identifier
from domain.observation import (
    Observation,
    ObservationType,
)
from domain.organization import (
    InMemoryOrganizationEventRepository,
    OrganizationEvent,
    OrganizationEventType,
    derive_source_event_id,
)
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)


def _make_communication(
    *,
    source_event_id: str | None = "comm-123",
    correlation_id: str = "thread-abc",
    occurred_at: datetime | None = None,
    actor_id: str = "user-1",
    source: EventSource = EventSource.SLACK,
) -> CommunicationEvent:
    now = occurred_at or datetime(2026, 10, 16, 15, 0, 0, tzinfo=timezone.utc)
    return CommunicationEvent(
        correlation_id=Identifier(business_id=correlation_id),
        source=source,
        source_event_id=source_event_id or "",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id=actor_id,
                external_ids={"slack": "U123"},
            ),
            display_name=actor_id,
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id=correlation_id,
                external_ids={"slack": "C123"},
            ),
            name="general",
            channel_type="slack",
        ),
        content=Content(
            body="Deploy the release to production.",
            metadata={"source_timestamp": now.isoformat()},
        ),
    )


def _make_event(
    event_type: OrganizationEventType = OrganizationEventType.TASK_CREATED,
    *,
    evidence: list[str] | None = None,
    correlation_id: str | Identifier | None = None,
    occurred_at: datetime | None = None,
    actor_id: str | None = None,
) -> OrganizationEvent:
    corr = (
        Identifier(business_id=correlation_id)
        if isinstance(correlation_id, str)
        else correlation_id
    )
    obs_meta = {"actor_id": actor_id} if actor_id else {}
    obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Deploy the release to production.",
        confidence=0.95,
        evidence=list(evidence) if evidence is not None else ["ev-orig-1"],
        correlation_id=corr,
        occurred_at=occurred_at,
        metadata=obs_meta,
    )
    return OrganizationEvent(
        event_type=event_type,
        summary="Deploy the release to production.",
        observations=[obs],
        confidence=0.95,
        correlation_id=corr,
        occurred_at=occurred_at,
    )


class StubExtractor:
    def __init__(self, observations: list[Observation]):
        self.observations = observations

    def extract(self, communication: Any) -> list[Observation]:
        return self.observations


class StubBuilder:
    def __init__(self, events: list[OrganizationEvent]):
        self.events = events

    def build(self, observations: list[Observation]) -> list[OrganizationEvent]:
        return self.events


def test_valid_source_event_id_is_preserved():
    """Requirement 1: A valid source event ID is preserved."""
    event = _make_event(evidence=["explicit-evidence-id"])
    comm = _make_communication(source_event_id="authoritative-source-id")

    resolved = derive_source_event_id(
        event,
        source_type="slack",
        communication=comm,
    )
    assert resolved == "authoritative-source-id"

    # When communication ID is empty but observation evidence is present
    comm_no_id = _make_communication(source_event_id="")
    resolved_evidence = derive_source_event_id(
        event,
        source_type="slack",
        communication=comm_no_id,
    )
    assert resolved_evidence == "explicit-evidence-id"


def test_missing_canonical_id_safely_recovered_when_stable_inputs_exist():
    """Requirement 2: A missing canonical ID is safely recovered when stable identity inputs exist."""
    occurred = datetime(2026, 10, 16, 12, 30, 0, tzinfo=timezone.utc)
    event = _make_event(
        evidence=[],
        correlation_id="meeting-456",
        occurred_at=occurred,
    )
    comm = _make_communication(
        source_event_id="",
        correlation_id="meeting-456",
        occurred_at=occurred,
        actor_id="alice",
        source=EventSource.MICROSOFT_TEAMS,
    )

    resolved = derive_source_event_id(
        event,
        source_type="microsoft_teams",
        correlation_id="meeting-456",
        communication=comm,
    )

    assert resolved is not None
    assert resolved.startswith("synthetic:microsoft_teams:meeting-456:")
    assert "2026-10-16T12:30:00+00:00" in resolved
    assert "alice" in resolved
    assert len(resolved) <= 255


def test_repeated_processing_produces_identical_fallback_id():
    """Requirement 3: Repeated processing produces the same fallback ID."""
    occurred = datetime(2026, 10, 16, 12, 30, 0, tzinfo=timezone.utc)
    event = _make_event(
        evidence=[],
        correlation_id="thread-777",
        occurred_at=occurred,
    )
    comm = _make_communication(
        source_event_id="",
        correlation_id="thread-777",
        occurred_at=occurred,
        actor_id="bob",
    )

    id_attempt_1 = derive_source_event_id(
        event,
        source_type="slack",
        correlation_id="thread-777",
        communication=comm,
    )
    id_attempt_2 = derive_source_event_id(
        event,
        source_type="slack",
        correlation_id="thread-777",
        communication=comm,
    )

    assert id_attempt_1 is not None
    assert id_attempt_1 == id_attempt_2


def test_insufficient_identity_information_follows_safe_failure_path(caplog):
    """Requirement 4: Missing or insufficient identity information follows the explicitly chosen safe failure path."""
    # Completely bare event with no correlation, no occurrence time, no evidence, no actor
    bare_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Orphan task with no provenance",
        confidence=0.5,
        evidence=[],
        correlation_id=None,
        occurred_at=None,
    )
    bare_event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Orphan task with no provenance",
        observations=[bare_obs],
        confidence=0.5,
        correlation_id=None,
        occurred_at=None,
    )

    # 1. Resolver returns None when identity cannot be established
    assert derive_source_event_id(bare_event) is None

    # 2. Repository raises ValueError if save is invoked with insufficient identity
    repo = InMemoryOrganizationEventRepository()
    with pytest.raises(ValueError, match="source_event_id cannot be empty"):
        repo.save(bare_event, source_type="slack", source_event_id=None)

    # 3. Pipeline skips event persistence with a structured warning log
    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=StubExtractor([bare_obs]),
        organization_builder=StubBuilder([bare_event]),
        knowledge_builder=MagicMock(),
        knowledge_validator=MagicMock(),
        knowledge_acceptance_service=MagicMock(),
        reasoning_service=None,
        organization_event_repository=repo,
    )

    bare_comm = MagicMock()
    bare_comm.source = "slack"
    bare_comm.source_event_id = ""
    bare_comm.correlation_id = None
    bare_comm.actor = None
    bare_comm.content = None

    caplog.set_level(logging.WARNING, logger="application.pipeline.pipeline")
    pipeline.process(bare_comm)

    # Confirm repository did not store the orphan event
    assert len(repo.all()) == 0

    # Confirm structured diagnostic warning was emitted
    warning_records = [
        r for r in caplog.records
        if r.name == "application.pipeline.pipeline" and r.levelname == "WARNING"
    ]
    assert any(
        getattr(r, "event", None) == "organization_event_missing_identity"
        for r in warning_records
    )


def test_existing_duplicate_suppression_remains_correct():
    """Requirement 5: Existing duplicate suppression remains correct with fallback IDs."""
    occurred = datetime(2026, 10, 16, 14, 0, 0, tzinfo=timezone.utc)
    event = _make_event(
        evidence=[],
        correlation_id="channel-dedup",
        occurred_at=occurred,
        actor_id="user-dedup",
    )
    repo = InMemoryOrganizationEventRepository()

    # Save once using deterministic fallback resolution
    repo.save(
        event,
        source_type="slack",
        source_event_id=None,
        correlation_id="channel-dedup",
    )
    assert len(repo.all()) == 1

    # Save second time (replay) - must deduplicate cleanly
    repo.save(
        event,
        source_type="slack",
        source_event_id=None,
        correlation_id="channel-dedup",
    )
    assert len(repo.all()) == 1


def test_unrelated_persistence_errors_still_propagate():
    """Requirement 6: Unrelated persistence errors still propagate."""
    class BrokenRepository:
        def save(self, *args, **kwargs):
            raise RuntimeError("Database connection timed out during transaction commit")

    occurred = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    event = _make_event(
        evidence=[],
        correlation_id="meeting-crash",
        occurred_at=occurred,
    )
    comm = _make_communication(
        source_event_id="",
        correlation_id="meeting-crash",
        occurred_at=occurred,
    )

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=StubExtractor(list(event.observations)),
        organization_builder=StubBuilder([event]),
        knowledge_builder=MagicMock(),
        knowledge_validator=MagicMock(),
        knowledge_acceptance_service=MagicMock(),
        reasoning_service=None,
        organization_event_repository=BrokenRepository(),
    )

    with pytest.raises(RuntimeError, match="Database connection timed out"):
        pipeline.process(comm)


def test_pipeline_skips_unidentifiable_event_without_corrupting_valid_events(caplog):
    """Requirement 7: The pipeline handles rejected/skipped events without corrupting valid events."""
    occurred = datetime(2026, 10, 16, 15, 0, 0, tzinfo=timezone.utc)

    # Event 1: Unidentifiable orphan (no correlation, no timestamp, no evidence)
    unidentifiable_obs = Observation(
        observation_type=ObservationType.TASK,
        summary="Malformed task with no identity",
        confidence=0.5,
        evidence=[],
        correlation_id=None,
        occurred_at=None,
    )
    unidentifiable_event = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Malformed task with no identity",
        observations=[unidentifiable_obs],
        confidence=0.5,
        correlation_id=None,
        occurred_at=None,
    )

    # Event 2: Valid event with complete identity
    valid_event = _make_event(
        event_type=OrganizationEventType.DECISION_MADE,
        evidence=["valid-source-seg-1"],
        correlation_id="meeting-clean",
        occurred_at=occurred,
    )

    repo = InMemoryOrganizationEventRepository()
    mock_ops = MagicMock()

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=StubExtractor([unidentifiable_obs, valid_event.observations[0]]),
        organization_builder=StubBuilder([unidentifiable_event, valid_event]),
        knowledge_builder=MagicMock(),
        knowledge_validator=MagicMock(),
        knowledge_acceptance_service=MagicMock(),
        reasoning_service=None,
        operational_item_service=None,
        operations_agent=mock_ops,
        organization_event_repository=repo,
    )

    comm = MagicMock()
    comm.source = "slack"
    comm.source_event_id = ""
    comm.correlation_id = None
    comm.actor = None
    comm.content = None

    caplog.set_level(logging.WARNING, logger="application.pipeline.pipeline")
    pipeline.process(comm)

    # Valid event was persisted
    stored = repo.all()
    assert len(stored) == 1
    assert stored[0].summary == valid_event.summary
    assert stored[0].event_type == OrganizationEventType.DECISION_MADE

    # Specialist was called only for the valid event
    assert mock_ops.process_event.call_count == 1
    call_args = mock_ops.process_event.call_args[0]
    assert call_args[0].summary == valid_event.summary

    # Diagnostic warning was logged for unidentifiable event
    warning_records = [
        r for r in caplog.records
        if r.name == "application.pipeline.pipeline" and r.levelname == "WARNING"
    ]
    assert any(
        getattr(r, "event", None) == "organization_event_missing_identity"
        for r in warning_records
    )


def test_missing_timestamp_with_actor_does_not_produce_synthetic_id():
    """Missing timestamp plus actor must not produce a synthetic ID."""
    event = _make_event(
        evidence=[],
        correlation_id="meeting-no-ts",
        occurred_at=None,
    )
    # Communication has actor but no source_timestamp and no occurred_at
    comm = CommunicationEvent(
        correlation_id=Identifier(business_id="meeting-no-ts"),
        source=EventSource.MICROSOFT_TEAMS,
        source_event_id="",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="alice",
                external_ids={"teams": "alice"},
            ),
            display_name="Alice",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="meeting-no-ts",
                external_ids={"teams": "meeting-no-ts"},
            ),
            name="Meeting No Timestamp",
            channel_type="meeting",
        ),
        content=Content(
            body="Task with actor but no occurrence timestamp.",
            metadata={},  # No source_timestamp
        ),
    )

    resolved = derive_source_event_id(
        event,
        source_type="microsoft_teams",
        correlation_id="meeting-no-ts",
        communication=comm,
    )

    # Must return None rather than collapsing events from alice into a synthetic ID
    assert resolved is None

    # Repository save must fail safe with ValueError
    repo = InMemoryOrganizationEventRepository()
    with pytest.raises(ValueError, match="source_event_id cannot be empty"):
        repo.save(
            event,
            source_type="microsoft_teams",
            source_event_id=None,
            correlation_id="meeting-no-ts",
        )


def test_equivalent_utc_and_offset_timestamps_produce_identical_id():
    """Equivalent UTC and offset timestamp representations produce the same ID."""
    dt_utc = datetime(2026, 10, 16, 12, 30, 0, tzinfo=timezone.utc)
    dt_offset = datetime(
        2026, 10, 16, 18, 0, 0,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    iso_z = "2026-10-16T12:30:00Z"
    iso_offset = "2026-10-16T18:00:00+05:30"
    epoch_float = 1792153800.0
    epoch_str = "1792153800.0"

    event_utc = _make_event(
        evidence=[], correlation_id="chan-equiv", occurred_at=dt_utc, actor_id="user-equiv"
    )
    event_offset = _make_event(
        evidence=[], correlation_id="chan-equiv", occurred_at=dt_offset, actor_id="user-equiv"
    )

    obs_iso_z = Observation(
        observation_type=ObservationType.TASK,
        summary="Equivalent task",
        confidence=0.9,
        evidence=[],
        correlation_id=Identifier(business_id="chan-equiv"),
        occurred_at=iso_z,
        metadata={"actor_id": "user-equiv"},
    )
    event_iso_z = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Equivalent task",
        observations=[obs_iso_z],
        confidence=0.9,
        correlation_id=Identifier(business_id="chan-equiv"),
        occurred_at=None,
    )

    obs_iso_offset = Observation(
        observation_type=ObservationType.TASK,
        summary="Equivalent task",
        confidence=0.9,
        evidence=[],
        correlation_id=Identifier(business_id="chan-equiv"),
        occurred_at=iso_offset,
        metadata={"actor_id": "user-equiv"},
    )
    event_iso_offset = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Equivalent task",
        observations=[obs_iso_offset],
        confidence=0.9,
        correlation_id=Identifier(business_id="chan-equiv"),
        occurred_at=None,
    )

    event_epoch = _make_event(
        evidence=[], correlation_id="chan-equiv", occurred_at=epoch_float, actor_id="user-equiv"
    )
    event_epoch_str = _make_event(
        evidence=[], correlation_id="chan-equiv", occurred_at=epoch_str, actor_id="user-equiv"
    )

    id_utc = derive_source_event_id(event_utc, source_type="slack", correlation_id="chan-equiv")
    id_offset = derive_source_event_id(
        event_offset, source_type="slack", correlation_id="chan-equiv"
    )
    id_iso_z = derive_source_event_id(
        event_iso_z, source_type="slack", correlation_id="chan-equiv"
    )
    id_iso_offset = derive_source_event_id(
        event_iso_offset, source_type="slack", correlation_id="chan-equiv"
    )
    id_epoch = derive_source_event_id(
        event_epoch, source_type="slack", correlation_id="chan-equiv"
    )
    id_epoch_str = derive_source_event_id(
        event_epoch_str, source_type="slack", correlation_id="chan-equiv"
    )

    expected = "synthetic:slack:chan-equiv:2026-10-16T12:30:00+00:00:user-equiv"
    assert id_utc == expected
    assert id_offset == expected
    assert id_iso_z == expected
    assert id_iso_offset == expected
    assert id_epoch == expected
    assert id_epoch_str == expected


def test_invalid_timestamp_does_not_produce_unstable_id():
    """Invalid timestamp inputs safely return None and do not generate unstable IDs."""
    invalid_inputs = [
        "not-a-valid-timestamp",
        "2026-99-99T99:99:99",
        "",
        [2026, 10, 16],
        {"bad": "timestamp"},
    ]

    for bad_ts in invalid_inputs:
        obs = Observation(
            observation_type=ObservationType.TASK,
            summary="Bad ts task",
            confidence=0.9,
            evidence=[],
            correlation_id=Identifier(business_id="chan-bad"),
            occurred_at=bad_ts,
        )
        event = OrganizationEvent(
            event_type=OrganizationEventType.TASK_CREATED,
            summary="Bad ts task",
            observations=[obs],
            confidence=0.9,
            correlation_id=Identifier(business_id="chan-bad"),
            occurred_at=None,
        )

        resolved = derive_source_event_id(
            event,
            source_type="slack",
            correlation_id="chan-bad",
        )
        assert resolved is None, f"Expected None for invalid timestamp: {bad_ts!r}"


def test_authoritative_source_ids_and_evidence_bypass_fallback_and_remain_unchanged():
    """Authoritative source IDs and evidence strings are preserved verbatim without normalization."""
    # Even with invalid timestamp and differing correlation, authoritative communication ID is preserved
    comm = _make_communication(
        source_event_id="authoritative-raw-msg-999:123",
        correlation_id="corr-auth",
        occurred_at=None,
    )
    obs = Observation(
        observation_type=ObservationType.DECISION,
        summary="Authoritative decision",
        confidence=0.95,
        evidence=["authoritative-segment-evidence:1:2"],
        correlation_id=None,
        occurred_at="invalid-date",
    )
    event = OrganizationEvent(
        event_type=OrganizationEventType.DECISION_MADE,
        summary="Authoritative decision",
        observations=[obs],
        confidence=0.95,
        correlation_id=None,
        occurred_at=None,
    )

    resolved_from_comm = derive_source_event_id(
        event,
        source_type="slack",
        communication=comm,
    )
    assert resolved_from_comm == "authoritative-raw-msg-999:123"

    # When communication ID is empty, authoritative evidence string is returned verbatim
    comm_empty = _make_communication(
        source_event_id="",
        correlation_id="corr-auth",
        occurred_at=None,
    )
    resolved_from_evidence = derive_source_event_id(
        event,
        source_type="slack",
        communication=comm_empty,
    )
    assert resolved_from_evidence == "authoritative-segment-evidence:1:2"


def test_missing_actor_with_valid_correlation_and_timestamp_returns_none():
    """Missing actor with valid correlation ID and timestamp must return None."""
    occurred = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    event = _make_event(
        evidence=[],
        correlation_id="meeting-no-actor",
        occurred_at=occurred,
        actor_id=None,
    )

    resolved = derive_source_event_id(
        event,
        source_type="microsoft_teams",
        correlation_id="meeting-no-actor",
    )
    assert resolved is None

    repo = InMemoryOrganizationEventRepository()
    with pytest.raises(ValueError, match="source_event_id cannot be empty"):
        repo.save(
            event,
            source_type="microsoft_teams",
            source_event_id=None,
            correlation_id="meeting-no-actor",
        )


def test_identical_source_correlation_timestamp_with_different_actors_produce_different_ids():
    """Identical source, correlation ID, and timestamp with different actor IDs produce different synthetic IDs."""
    occurred = datetime(2026, 10, 16, 16, 45, 0, tzinfo=timezone.utc)
    event_alice = _make_event(
        evidence=[],
        correlation_id="thread-shared-ts",
        occurred_at=occurred,
        actor_id="alice",
    )
    event_bob = _make_event(
        evidence=[],
        correlation_id="thread-shared-ts",
        occurred_at=occurred,
        actor_id="bob",
    )

    id_alice = derive_source_event_id(
        event_alice,
        source_type="slack",
        correlation_id="thread-shared-ts",
    )
    id_bob = derive_source_event_id(
        event_bob,
        source_type="slack",
        correlation_id="thread-shared-ts",
    )

    assert id_alice is not None
    assert id_bob is not None
    assert id_alice != id_bob
    assert id_alice.endswith(":alice")
    assert id_bob.endswith(":bob")


def test_authoritative_ids_resolve_successfully_when_actor_or_timestamp_missing():
    """Existing authoritative IDs still resolve successfully when actor or timestamp data is missing."""
    # 1. Authoritative communication source_event_id succeeds without actor or timestamp
    comm = _make_communication(
        source_event_id="authoritative-msg-123",
        correlation_id="chan-auth",
        occurred_at=None,
    )
    # Ensure communication has no actor
    object.__setattr__(comm, "actor", None)

    event_bare = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Task without actor or timestamp",
        observations=[],
        confidence=0.9,
        correlation_id=Identifier(business_id="chan-auth"),
        occurred_at=None,
    )
    resolved_comm = derive_source_event_id(
        event_bare,
        source_type="slack",
        communication=comm,
    )
    assert resolved_comm == "authoritative-msg-123"

    # 2. Authoritative observation evidence succeeds without actor or timestamp
    obs_evidence = Observation(
        observation_type=ObservationType.TASK,
        summary="Evidence task",
        confidence=0.9,
        evidence=["authoritative-ev-456"],
        correlation_id=None,
        occurred_at=None,
        metadata={},
    )
    event_evidence = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Evidence task",
        observations=[obs_evidence],
        confidence=0.9,
        correlation_id=None,
        occurred_at=None,
    )
    resolved_evidence = derive_source_event_id(
        event_evidence,
        source_type="slack",
    )
    assert resolved_evidence == "authoritative-ev-456"

    # 3. Observation metadata source_event_id succeeds without actor or timestamp
    obs_meta = Observation(
        observation_type=ObservationType.TASK,
        summary="Meta task",
        confidence=0.9,
        evidence=[],
        correlation_id=None,
        occurred_at=None,
        metadata={"source_event_id": "authoritative-meta-789"},
    )
    event_meta = OrganizationEvent(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Meta task",
        observations=[obs_meta],
        confidence=0.9,
        correlation_id=None,
        occurred_at=None,
    )
    resolved_meta = derive_source_event_id(
        event_meta,
        source_type="slack",
    )
    assert resolved_meta == "authoritative-meta-789"
