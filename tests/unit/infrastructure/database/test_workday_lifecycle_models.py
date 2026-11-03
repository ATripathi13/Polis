"""
Offline unit tests for WorkdaySessionModel and PersonPreferenceModel SQLAlchemy ORM schemas.

Validates table schemas, column types, nullability, defaults, index definitions,
and uniqueness constraints using pure SQLAlchemy metadata inspection (no database connection).
"""

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from domain.activity import SignoffReminderPolicy, WorkdaySessionStatus
from infrastructure.database.models import (
    PersonPreferenceModel,
    WorkdaySessionModel,
)


# =====================================================================
# 1. WorkdaySessionModel Table and Column Specifications
# =====================================================================


def test_workday_session_table_name():
    assert WorkdaySessionModel.__tablename__ == "workday_sessions"


def test_workday_session_columns_and_types():
    table = WorkdaySessionModel.__table__
    cols = table.columns

    # id (PK)
    assert cols["id"].primary_key is True
    assert isinstance(cols["id"].type, String)
    assert cols["id"].type.length == 36
    assert cols["id"].nullable is False

    # person_id
    assert isinstance(cols["person_id"].type, String)
    assert cols["person_id"].type.length == 255
    assert cols["person_id"].nullable is False

    # person_name
    assert isinstance(cols["person_name"].type, String)
    assert cols["person_name"].type.length == 255
    assert cols["person_name"].nullable is False

    # work_date
    assert isinstance(cols["work_date"].type, Date)
    assert cols["work_date"].nullable is False

    # status
    assert isinstance(cols["status"].type, String)
    assert cols["status"].type.length == 50
    assert cols["status"].nullable is False

    # started_at
    assert isinstance(cols["started_at"].type, DateTime)
    assert cols["started_at"].type.timezone is True
    assert cols["started_at"].nullable is False

    # ended_at (nullable)
    assert isinstance(cols["ended_at"].type, DateTime)
    assert cols["ended_at"].type.timezone is True
    assert cols["ended_at"].nullable is True

    # briefing_sent_at (nullable)
    assert isinstance(cols["briefing_sent_at"].type, DateTime)
    assert cols["briefing_sent_at"].type.timezone is True
    assert cols["briefing_sent_at"].nullable is True

    # total_work_minutes
    assert isinstance(cols["total_work_minutes"].type, Integer)
    assert cols["total_work_minutes"].nullable is False
    assert cols["total_work_minutes"].default.arg == 0

    # total_break_minutes
    assert isinstance(cols["total_break_minutes"].type, Integer)
    assert cols["total_break_minutes"].nullable is False
    assert cols["total_break_minutes"].default.arg == 0

    # timezone
    assert isinstance(cols["timezone"].type, String)
    assert cols["timezone"].type.length == 100
    assert cols["timezone"].nullable is False

    # start_source_event_id (nullable)
    assert isinstance(cols["start_source_event_id"].type, String)
    assert cols["start_source_event_id"].type.length == 255
    assert cols["start_source_event_id"].nullable is True

    # end_source_event_id (nullable)
    assert isinstance(cols["end_source_event_id"].type, String)
    assert cols["end_source_event_id"].type.length == 255
    assert cols["end_source_event_id"].nullable is True

    # business_id
    assert isinstance(cols["business_id"].type, String)
    assert cols["business_id"].type.length == 255
    assert cols["business_id"].nullable is False
    assert cols["business_id"].default.arg == ""

    # metadata_ -> "metadata" column
    assert "metadata" in cols
    assert isinstance(cols["metadata"].type, JSONB)
    assert cols["metadata"].nullable is False
    assert callable(cols["metadata"].default.arg)
    assert cols["metadata"].default.arg(None) == {}

    # created_at
    assert isinstance(cols["created_at"].type, DateTime)
    assert cols["created_at"].type.timezone is True
    assert cols["created_at"].nullable is False

    # updated_at
    assert isinstance(cols["updated_at"].type, DateTime)
    assert cols["updated_at"].type.timezone is True
    assert cols["updated_at"].nullable is False


# =====================================================================
# 2. WorkdaySessionModel Indexes & Constraints
# =====================================================================


def test_workday_session_indexes_exist():
    table = WorkdaySessionModel.__table__
    index_names = {idx.name for idx in table.indexes}

    # Column-level indexes
    assert "ix_workday_sessions_person_id" in index_names
    assert "ix_workday_sessions_work_date" in index_names
    assert "ix_workday_sessions_status" in index_names

    # Table-level composite indexes
    assert "ix_workday_sessions_person_work_date" in index_names
    assert "ix_workday_sessions_person_started_at" in index_names

    # Table-level partial unique index
    assert "uq_workday_sessions_active_person" in index_names


def test_workday_session_partial_unique_index_predicate():
    table = WorkdaySessionModel.__table__
    active_idx = next(
        idx for idx in table.indexes if idx.name == "uq_workday_sessions_active_person"
    )

    assert active_idx.unique is True
    assert [c.name for c in active_idx.columns] == ["person_id"]

    where_clause = active_idx.dialect_options.get("postgresql", {}).get("where")
    assert where_clause is not None
    assert str(where_clause) == "status = 'active'"


def test_no_unique_constraint_on_person_and_work_date():
    table = WorkdaySessionModel.__table__

    # Verify no unique constraint on (person_id, work_date)
    for uq in table.constraints:
        cols = {c.name for c in uq.columns}
        if cols == {"person_id", "work_date"}:
            pytest.fail("Found illegal unique constraint on (person_id, work_date)!")

    # Verify no unique index on (person_id, work_date)
    for idx in table.indexes:
        cols = {c.name for c in idx.columns}
        if cols == {"person_id", "work_date"} and idx.unique:
            pytest.fail("Found illegal unique index on (person_id, work_date)!")


def test_workday_session_enum_compatibility():
    # Verify values match WorkdaySessionStatus enum strings
    valid_statuses = {s.value for s in WorkdaySessionStatus}
    assert valid_statuses == {"active", "closed", "abandoned"}

    model = WorkdaySessionModel(
        id="sess-001",
        person_id="U100",
        person_name="Alice",
        work_date=Date(),
        status=WorkdaySessionStatus.ACTIVE.value,
        timezone="UTC",
    )
    assert model.status == "active"


# =====================================================================
# 3. PersonPreferenceModel Table and Column Specifications
# =====================================================================


def test_person_preference_table_name():
    assert PersonPreferenceModel.__tablename__ == "person_preferences"


def test_person_preference_columns_and_types():
    table = PersonPreferenceModel.__table__
    cols = table.columns

    # id (PK)
    assert cols["id"].primary_key is True
    assert isinstance(cols["id"].type, String)
    assert cols["id"].type.length == 36
    assert cols["id"].nullable is False

    # person_id
    assert isinstance(cols["person_id"].type, String)
    assert cols["person_id"].type.length == 255
    assert cols["person_id"].nullable is False

    # reminders_after_signoff
    assert isinstance(cols["reminders_after_signoff"].type, String)
    assert cols["reminders_after_signoff"].type.length == 50
    assert cols["reminders_after_signoff"].nullable is False
    assert cols["reminders_after_signoff"].default.arg == "continue"

    # preferred_timezone (nullable)
    assert isinstance(cols["preferred_timezone"].type, String)
    assert cols["preferred_timezone"].type.length == 100
    assert cols["preferred_timezone"].nullable is True

    # business_id
    assert isinstance(cols["business_id"].type, String)
    assert cols["business_id"].type.length == 255
    assert cols["business_id"].nullable is False
    assert cols["business_id"].default.arg == ""

    # metadata_ -> "metadata" column
    assert "metadata" in cols
    assert isinstance(cols["metadata"].type, JSONB)
    assert cols["metadata"].nullable is False
    assert callable(cols["metadata"].default.arg)
    assert cols["metadata"].default.arg(None) == {}

    # created_at
    assert isinstance(cols["created_at"].type, DateTime)
    assert cols["created_at"].type.timezone is True
    assert cols["created_at"].nullable is False

    # updated_at
    assert isinstance(cols["updated_at"].type, DateTime)
    assert cols["updated_at"].type.timezone is True
    assert cols["updated_at"].nullable is False


# =====================================================================
# 4. PersonPreferenceModel Uniqueness & Enum Compatibility
# =====================================================================


def test_person_preference_single_named_uniqueness_on_person_id():
    table = PersonPreferenceModel.__table__

    # 1. person_id column itself must NOT have unique=True
    assert table.columns["person_id"].unique is not True

    # 2. Table-level UniqueConstraints must contain exactly one named constraint for person_id
    person_id_uqs = [
        c for c in table.constraints
        if {col.name for col in c.columns} == {"person_id"}
    ]
    assert len(person_id_uqs) == 1
    assert person_id_uqs[0].name == "uq_person_preferences_person_id"


def test_person_preference_enum_compatibility():
    valid_policies = {p.value for p in SignoffReminderPolicy}
    assert valid_policies == {"continue", "pause_until_next_workday"}

    model = PersonPreferenceModel(
        id="pref-001",
        person_id="U100",
        reminders_after_signoff=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY.value,
        preferred_timezone="America/New_York",
    )
    assert model.reminders_after_signoff == "pause_until_next_workday"
