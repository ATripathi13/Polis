from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from domain.activity import (
    WorkdaySession,
    WorkdaySessionStatus,
)
from domain.common.identifier import Identifier
from infrastructure.database import workday_session_repository as repo_module
from infrastructure.database.models import WorkdaySessionModel
from infrastructure.database.workday_session_repository import (
    PostgreSQLWorkdaySessionRepository,
)


def compile_filter(expr) -> str:
    """Compile a SQLAlchemy expression into a deterministic literal string."""
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def make_workday_session(
    person_id: str = "U100",
    person_name: str = "Test Person",
    work_date: date | None = None,
    started_at: datetime | None = None,
    timezone_str: str = "UTC",
    status: WorkdaySessionStatus = WorkdaySessionStatus.ACTIVE,
    ended_at: datetime | None = None,
    briefing_sent_at: datetime | None = None,
    total_work_minutes: int = 0,
    total_break_minutes: int = 0,
    start_source_event_id: str | None = None,
    end_source_event_id: str | None = None,
    business_id: str = "BIZ-100",
    metadata: dict | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> WorkdaySession:
    d = work_date or date(2026, 11, 2)
    s = started_at or datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    e = ended_at
    if status in (WorkdaySessionStatus.CLOSED, WorkdaySessionStatus.ABANDONED) and e is None:
        e = s + timedelta(hours=8)

    return WorkdaySession(
        identifier=Identifier(graph_id=uuid4(), business_id=business_id),
        person_id=person_id,
        person_name=person_name,
        work_date=d,
        started_at=s,
        timezone=timezone_str,
        status=status,
        ended_at=e,
        briefing_sent_at=briefing_sent_at,
        total_work_minutes=total_work_minutes,
        total_break_minutes=total_break_minutes,
        start_source_event_id=start_source_event_id,
        end_source_event_id=end_source_event_id,
        metadata=dict(metadata or {"role": "engineer", "team": "polis"}),
        created_at=created_at or datetime(2026, 11, 2, 9, 0, 0, tzinfo=timezone.utc),
        updated_at=updated_at or datetime(2026, 11, 2, 9, 0, 0, tzinfo=timezone.utc),
    )


def make_workday_model(
    session: WorkdaySession | None = None,
    id_str: str | None = None,
    person_id: str = "U100",
    person_name: str = "Test Person",
    work_date: date | None = None,
    status: str = "active",
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    briefing_sent_at: datetime | None = None,
    total_work_minutes: int = 0,
    total_break_minutes: int = 0,
    timezone_str: str = "UTC",
    start_source_event_id: str | None = None,
    end_source_event_id: str | None = None,
    business_id: str = "BIZ-100",
    metadata: dict | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> WorkdaySessionModel:
    if session is not None:
        return WorkdaySessionModel(
            id=str(session.identifier.graph_id),
            person_id=session.person_id,
            person_name=session.person_name,
            work_date=session.work_date,
            status=session.status.value,
            started_at=session.started_at,
            ended_at=session.ended_at,
            briefing_sent_at=session.briefing_sent_at,
            total_work_minutes=session.total_work_minutes,
            total_break_minutes=session.total_break_minutes,
            timezone=session.timezone,
            start_source_event_id=session.start_source_event_id,
            end_source_event_id=session.end_source_event_id,
            business_id=session.identifier.business_id,
            metadata_=dict(session.metadata),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    return WorkdaySessionModel(
        id=id_str or str(uuid4()),
        person_id=person_id,
        person_name=person_name,
        work_date=work_date or date(2026, 11, 2),
        status=status,
        started_at=started_at or datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
        ended_at=ended_at,
        briefing_sent_at=briefing_sent_at,
        total_work_minutes=total_work_minutes,
        total_break_minutes=total_break_minutes,
        timezone=timezone_str,
        start_source_event_id=start_source_event_id,
        end_source_event_id=end_source_event_id,
        business_id=business_id,
        metadata_=dict(metadata or {"role": "engineer", "team": "polis"}),
        created_at=created_at or datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
        updated_at=updated_at or datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
    )


class FakeQuery:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.filters = []
        self.ordering = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *expressions):
        self.ordering.extend(expressions)
        return self

    def first(self):
        return self.records[0] if self.records else None

    def all(self):
        return list(self.records)


class FakeSession:
    def __init__(self, records=None):
        self.query_instance = FakeQuery(records)
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.queried_model = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True
        return False

    def query(self, model):
        self.queried_model = model
        return self.query_instance

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# =====================================================================
# 1. New Session Insert and Complete ORM Field Mapping
# =====================================================================


def test_save_new_session_inserts_record_with_complete_orm_mapping():
    ws = make_workday_session(
        person_id="U100",
        person_name="Alice Smith",
        work_date=date(2026, 11, 2),
        started_at=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
        timezone_str="America/New_York",
        status=WorkdaySessionStatus.ACTIVE,
        ended_at=None,
        briefing_sent_at=datetime(2026, 11, 2, 9, 15, tzinfo=timezone.utc),
        total_work_minutes=120,
        total_break_minutes=15,
        start_source_event_id="evt-start-1",
        end_source_event_id=None,
        business_id="BIZ-ALICE-1",
        metadata={"project": "polis", "priority": "high"},
        created_at=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc),
    )

    session = FakeSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    repo.save(ws)

    assert len(session.added) == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True

    record = session.added[0]
    assert isinstance(record, WorkdaySessionModel)
    assert record.id == str(ws.identifier.graph_id)
    assert record.person_id == "U100"
    assert record.person_name == "Alice Smith"
    assert record.work_date == date(2026, 11, 2)
    assert record.status == "active"
    assert record.started_at == ws.started_at
    assert record.ended_at is None
    assert record.briefing_sent_at == ws.briefing_sent_at
    assert record.total_work_minutes == 120
    assert record.total_break_minutes == 15
    assert record.timezone == "America/New_York"
    assert record.start_source_event_id == "evt-start-1"
    assert record.end_source_event_id is None
    assert record.business_id == "BIZ-ALICE-1"
    assert record.metadata_ == {"project": "polis", "priority": "high"}
    assert record.created_at == ws.created_at
    assert record.updated_at == ws.updated_at


# =====================================================================
# 2. Existing Session Update Without Duplicate Insertion
# =====================================================================


def test_save_updates_existing_session_in_place_without_duplicate_insert():
    ws_initial = make_workday_session(
        person_id="U100",
        status=WorkdaySessionStatus.ACTIVE,
    )
    existing_record = make_workday_model(session=ws_initial)

    # Transition session to CLOSED with updated metrics
    end_time = ws_initial.started_at + timedelta(hours=8)
    ws_updated = WorkdaySession(
        identifier=ws_initial.identifier,
        person_id="U100",
        person_name="Alice Smith Updated",
        work_date=ws_initial.work_date,
        started_at=ws_initial.started_at,
        timezone=ws_initial.timezone,
        status=WorkdaySessionStatus.CLOSED,
        ended_at=end_time,
        briefing_sent_at=ws_initial.started_at + timedelta(minutes=10),
        total_work_minutes=480,
        total_break_minutes=45,
        start_source_event_id=ws_initial.start_source_event_id,
        end_source_event_id="evt-end-1",
        metadata={"phase": "completed"},
        created_at=ws_initial.created_at,
        updated_at=end_time,
    )

    session = FakeSession([existing_record])
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    repo.save(ws_updated)

    assert len(session.added) == 0  # Updated in place, not inserted
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True

    # Verify fields on the existing record were mutated in place
    assert existing_record.status == "closed"
    assert existing_record.person_name == "Alice Smith Updated"
    assert existing_record.ended_at == end_time
    assert existing_record.end_source_event_id == "evt-end-1"
    assert existing_record.total_work_minutes == 480
    assert existing_record.total_break_minutes == 45
    assert existing_record.metadata_ == {"phase": "completed"}
    assert existing_record.updated_at == end_time


# =====================================================================
# 3. Domain Reconstruction and Identifier Round-Trip
# =====================================================================


def test_to_domain_restores_identifier_uuid_and_business_id():
    fixed_uuid = uuid4()
    record = make_workday_model(
        id_str=str(fixed_uuid),
        business_id="BUSINESS-ID-XYZ",
        person_id="U200",
        person_name="Bob Jones",
        status="active",
    )

    domain_session = PostgreSQLWorkdaySessionRepository._to_domain(record)

    assert isinstance(domain_session, WorkdaySession)
    assert domain_session.identifier.graph_id == fixed_uuid
    assert domain_session.identifier.business_id == "BUSINESS-ID-XYZ"
    assert domain_session.person_id == "U200"
    assert domain_session.person_name == "Bob Jones"
    assert domain_session.status == WorkdaySessionStatus.ACTIVE


@pytest.mark.parametrize(
    ("status_str", "expected_enum"),
    [
        ("active", WorkdaySessionStatus.ACTIVE),
        ("closed", WorkdaySessionStatus.CLOSED),
        ("abandoned", WorkdaySessionStatus.ABANDONED),
    ],
)
def test_status_enum_round_trip(status_str, expected_enum):
    s_at = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    e_at = s_at + timedelta(hours=8) if expected_enum != WorkdaySessionStatus.ACTIVE else None
    record = make_workday_model(
        status=status_str,
        started_at=s_at,
        ended_at=e_at,
    )

    domain_session = PostgreSQLWorkdaySessionRepository._to_domain(record)
    assert domain_session.status == expected_enum


def test_metadata_defensive_copying():
    original_meta = {"key": "initial_value", "nested": {"count": 1}}
    record = make_workday_model(metadata=original_meta)

    domain_session = PostgreSQLWorkdaySessionRepository._to_domain(record)
    assert domain_session.metadata == original_meta

    # Mutating domain aggregate metadata does not affect record
    domain_session.metadata["key"] = "mutated_value"
    assert record.metadata_["key"] == "initial_value"

    # Saving aggregate copies metadata defensively into record
    session = FakeSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)
    repo.save(domain_session)

    saved_record = session.added[0]
    domain_session.metadata["key"] = "second_mutation"
    assert saved_record.metadata_["key"] == "mutated_value"


# =====================================================================
# 4. Query Behavior: find_active
# =====================================================================


def test_find_active_filters_by_person_id_and_active_status():
    record = make_workday_model(person_id="U100", status="active")
    session = FakeSession([record])
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    result = repo.find_active("U100")

    assert result is not None
    assert result.person_id == "U100"
    assert result.status == WorkdaySessionStatus.ACTIVE
    assert session.commits == 0
    assert session.closed is True

    compiled = [compile_filter(f) for f in session.query_instance.filters]
    assert "workday_sessions.person_id = 'U100'" in compiled
    assert "workday_sessions.status = 'active'" in compiled


def test_find_active_returns_none_when_empty():
    session = FakeSession([])
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    result = repo.find_active("U_NONE")

    assert result is None
    assert session.commits == 0
    assert session.closed is True


# =====================================================================
# 5. Query Behavior: find_latest_for_person
# =====================================================================


def test_find_latest_for_person_uses_both_ordering_clauses():
    record = make_workday_model(person_id="U100", status="closed", ended_at=datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc))
    session = FakeSession([record])
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    result = repo.find_latest_for_person("U100")

    assert result is not None
    assert result.person_id == "U100"
    assert session.commits == 0
    assert session.closed is True

    compiled = [compile_filter(f) for f in session.query_instance.filters]
    assert "workday_sessions.person_id = 'U100'" in compiled

    assert len(session.query_instance.ordering) == 2
    assert str(session.query_instance.ordering[0]) == "workday_sessions.started_at DESC"
    assert str(session.query_instance.ordering[1]) == "workday_sessions.created_at DESC"


def test_find_latest_for_person_returns_none_when_empty():
    session = FakeSession([])
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    result = repo.find_latest_for_person("U_UNKNOWN")

    assert result is None
    assert session.commits == 0
    assert session.closed is True


# =====================================================================
# 6. Query Behavior: find_for_person_on_date & Split Shifts
# =====================================================================


def test_find_for_person_on_date_filters_and_orders_chronologically():
    target_date = date(2026, 11, 2)
    s1_start = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
    s2_start = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)

    # Split shift on the same calendar date
    r1 = make_workday_model(
        person_id="U100",
        work_date=target_date,
        started_at=s1_start,
        status="closed",
        ended_at=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
    )
    r2 = make_workday_model(
        person_id="U100",
        work_date=target_date,
        started_at=s2_start,
        status="closed",
        ended_at=datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc),
    )

    session = FakeSession([r1, r2])
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    results = repo.find_for_person_on_date("U100", target_date)

    assert len(results) == 2
    assert results[0].started_at == s1_start
    assert results[1].started_at == s2_start
    assert session.commits == 0
    assert session.closed is True

    compiled = [compile_filter(f) for f in session.query_instance.filters]
    assert "workday_sessions.person_id = 'U100'" in compiled
    assert "workday_sessions.work_date = '2026-11-02'" in compiled

    assert len(session.query_instance.ordering) == 1
    assert str(session.query_instance.ordering[0]) == "workday_sessions.started_at ASC"


def test_no_query_imposes_uniqueness_on_work_date():
    """Verify that multiple sessions on the same work_date are returned without error."""
    target_date = date(2026, 11, 2)
    records = [
        make_workday_model(
            person_id="U100",
            work_date=target_date,
            status="closed",
            ended_at=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
        ),
        make_workday_model(
            person_id="U100",
            work_date=target_date,
            status="active",
        ),
    ]

    session = FakeSession(records)
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    results = repo.find_for_person_on_date("U100", target_date)
    assert len(results) == 2


# =====================================================================
# 7. Concurrency & Partial Unique Index Error Handling
# =====================================================================


def test_partial_unique_index_is_authoritative_no_app_precheck():
    """
    Verify that save() does NOT perform an application-level pre-check for
    active sessions. It only queries by primary key (id).
    """
    ws = make_workday_session(status=WorkdaySessionStatus.ACTIVE)
    session = FakeSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    repo.save(ws)

    # Exactly one filter for primary key lookup
    assert len(session.query_instance.filters) == 1
    compiled = compile_filter(session.query_instance.filters[0])
    assert f"workday_sessions.id = '{ws.identifier.graph_id}'" in compiled


def test_active_index_integrity_error_via_diag_rolls_back_and_becomes_value_error():
    diag = SimpleNamespace(constraint_name="uq_workday_sessions_active_person")
    orig = SimpleNamespace(diag=diag)
    error = IntegrityError("duplicate key value", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)
    ws = make_workday_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)

    with pytest.raises(
        ValueError,
        match="Person 'U100' already has an active workday session",
    ):
        repo.save(ws)

    assert session.commits == 1
    assert session.rollbacks == 1
    assert session.closed is True


def test_active_index_integrity_error_via_orig_constraint_rolls_back_and_becomes_value_error():
    orig = SimpleNamespace(constraint_name="uq_workday_sessions_active_person")
    error = IntegrityError("duplicate key value", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)
    ws = make_workday_session(person_id="U200", status=WorkdaySessionStatus.ACTIVE)

    with pytest.raises(
        ValueError,
        match="Person 'U200' already has an active workday session",
    ):
        repo.save(ws)

    assert session.rollbacks == 1
    assert session.closed is True


def test_active_index_integrity_error_via_message_fallback_rolls_back_and_becomes_value_error():
    orig = Exception('violates unique constraint "uq_workday_sessions_active_person"')
    error = IntegrityError("duplicate", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)
    ws = make_workday_session(person_id="U300", status=WorkdaySessionStatus.ACTIVE)

    with pytest.raises(
        ValueError,
        match="Person 'U300' already has an active workday session",
    ):
        repo.save(ws)

    assert session.rollbacks == 1
    assert session.closed is True


def test_unrelated_integrity_error_with_diag_rolls_back_and_is_reraised():
    diag = SimpleNamespace(constraint_name="fk_some_other_constraint")
    orig = SimpleNamespace(diag=diag)
    error = IntegrityError("foreign key violation", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)
    ws = make_workday_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)

    with pytest.raises(IntegrityError) as exc_info:
        repo.save(ws)

    assert exc_info.value is error
    assert session.commits == 1
    assert session.rollbacks == 1
    assert session.closed is True


def test_unrelated_integrity_error_with_unrelated_message_rolls_back_and_is_reraised():
    orig = Exception('duplicate key value violates unique constraint "uq_unrelated_table_col"')
    error = IntegrityError("duplicate", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)
    ws = make_workday_session(person_id="U100", status=WorkdaySessionStatus.ACTIVE)

    with pytest.raises(IntegrityError) as exc_info:
        repo.save(ws)

    assert exc_info.value is error
    assert session.rollbacks == 1
    assert session.closed is True


# =====================================================================
# 8. Query and Input Validation
# =====================================================================


def test_save_rejects_non_workday_session_instance():
    session = FakeSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    with pytest.raises(TypeError, match="session must be an instance of WorkdaySession"):
        repo.save("not-a-session")  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_id", ["", "   ", None, 12345, []])
def test_queries_reject_invalid_person_id(invalid_id):
    session = FakeSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_active(invalid_id)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_latest_for_person(invalid_id)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_for_person_on_date(invalid_id, date(2026, 11, 2))  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_date", [None, "2026-11-02", datetime.now(), 12345])
def test_find_for_person_on_date_rejects_invalid_date(invalid_date):
    session = FakeSession()
    repo = PostgreSQLWorkdaySessionRepository(session_factory=lambda: session)

    with pytest.raises(ValueError, match="work_date must be a valid date"):
        repo.find_for_person_on_date("U100", invalid_date)  # type: ignore[arg-type]


# =====================================================================
# 9. Default SessionLocal Resolution via Module Monkeypatching
# =====================================================================


def test_default_session_local_used_when_session_factory_omitted(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(repo_module, "SessionLocal", lambda: session)

    repo = PostgreSQLWorkdaySessionRepository()
    ws = make_workday_session(person_id="U100")

    repo.save(ws)

    assert len(session.added) == 1
    assert session.commits == 1
    assert session.closed is True
