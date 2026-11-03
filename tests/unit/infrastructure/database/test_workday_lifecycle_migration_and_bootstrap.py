"""
Offline Unit Tests for Workday Lifecycle Migration and Application Bootstrap Integration.

Validates:
1. Alembic migration c8e1a4d2f635 revision, down_revision, schema, indexes, constraints, and downgrade operations.
2. Safety gate registration and session factory redirection for both repositories.
3. ApplicationContainer structure and bootstrap() instantiation / wiring.

DO NOT CONNECT TO POSTGRESQL.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest

from domain.activity.repositories import (
    PersonPreferenceRepository,
    WorkdaySessionRepository,
)
from infrastructure.database import (
    PostgreSQLPersonPreferenceRepository,
    PostgreSQLWorkdaySessionRepository,
)
from application.bootstrap.container import ApplicationContainer
from tests.staging_safety_gate import (
    ALL_SESSION_MODULES,
    redirect_session_factories,
)


# ---------------------------------------------------------------------------
# Migration Module Loader
# ---------------------------------------------------------------------------

def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[4]
        / "alembic"
        / "versions"
        / "c8e1a4d2f635_create_workday_lifecycle_tables.py"
    )
    assert migration_path.exists(), f"Migration file not found at {migration_path}"
    spec = importlib.util.spec_from_file_location("c8e1a4d2f635", migration_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Migration Tests (Offline Operation Capture)
# ---------------------------------------------------------------------------

def test_migration_revision_and_down_revision():
    """Verify revision and down_revision match the required chain."""
    mod = _load_migration_module()
    assert mod.revision == "c8e1a4d2f635"
    assert mod.down_revision == "b4f8c92e1a35"


def test_migration_upgrade_workday_sessions_table_and_indexes():
    """Verify upgrade creates workday_sessions table with expected columns and indexes."""
    mod = _load_migration_module()

    created_tables: dict[str, list] = {}
    created_indexes: list[dict] = []

    def fake_create_table(name, *args, **kwargs):
        created_tables[name] = list(args)

    def fake_create_index(name, table_name, columns, **kwargs):
        created_indexes.append({
            "name": name,
            "table_name": table_name,
            "columns": columns,
            "kwargs": kwargs,
        })

    with patch.object(mod.op, "create_table", side_effect=fake_create_table), \
         patch.object(mod.op, "create_index", side_effect=fake_create_index):
        mod.upgrade()

    assert "workday_sessions" in created_tables
    ws_elements = created_tables["workday_sessions"]

    # Extract columns
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    col_map = {elem.name: elem for elem in ws_elements if isinstance(elem, sa.Column)}

    expected_cols = {
        "id", "person_id", "person_name", "work_date", "status",
        "started_at", "ended_at", "briefing_sent_at", "total_work_minutes",
        "total_break_minutes", "timezone", "start_source_event_id",
        "end_source_event_id", "business_id", "metadata", "created_at", "updated_at",
    }
    assert expected_cols.issubset(set(col_map.keys()))

    # Column type and nullability assertions
    assert not col_map["id"].nullable
    assert not col_map["person_id"].nullable
    assert not col_map["person_name"].nullable
    assert not col_map["work_date"].nullable
    assert not col_map["status"].nullable
    assert not col_map["started_at"].nullable
    assert col_map["ended_at"].nullable
    assert col_map["briefing_sent_at"].nullable
    assert not col_map["total_work_minutes"].nullable
    assert not col_map["total_break_minutes"].nullable
    assert not col_map["timezone"].nullable
    assert col_map["start_source_event_id"].nullable
    assert col_map["end_source_event_id"].nullable
    assert not col_map["business_id"].nullable
    assert not col_map["metadata"].nullable
    assert not col_map["created_at"].nullable
    assert not col_map["updated_at"].nullable

    # Verify JSONB type for metadata
    assert isinstance(col_map["metadata"].type, postgresql.JSONB)

    # Indexes on workday_sessions
    ws_indexes = [idx for idx in created_indexes if idx["table_name"] == "workday_sessions"]
    ws_idx_names = {idx["name"] for idx in ws_indexes}

    expected_idx_names = {
        "ix_workday_sessions_person_id",
        "ix_workday_sessions_work_date",
        "ix_workday_sessions_status",
        "ix_workday_sessions_start_source_event_id",
        "ix_workday_sessions_end_source_event_id",
        "ix_workday_sessions_person_work_date",
        "ix_workday_sessions_person_started_at",
        "uq_workday_sessions_active_person",
    }
    assert ws_idx_names == expected_idx_names

    # Verify partial unique index for active sessions per person
    active_idx = next(idx for idx in ws_indexes if idx["name"] == "uq_workday_sessions_active_person")
    assert active_idx["columns"] == ["person_id"]
    assert active_idx["kwargs"].get("unique") is True
    where_clause = str(active_idx["kwargs"].get("postgresql_where"))
    assert "status = 'active'" in where_clause

    # Verify NO unique index on (person_id, work_date)
    person_work_date_idx = next(idx for idx in ws_indexes if idx["name"] == "ix_workday_sessions_person_work_date")
    assert person_work_date_idx["kwargs"].get("unique") is not True


def test_migration_upgrade_person_preferences_table_and_constraints():
    """Verify upgrade creates person_preferences table with unique constraint and indexes."""
    mod = _load_migration_module()

    created_tables: dict[str, list] = {}
    created_indexes: list[dict] = []

    def fake_create_table(name, *args, **kwargs):
        created_tables[name] = list(args)

    def fake_create_index(name, table_name, columns, **kwargs):
        created_indexes.append({
            "name": name,
            "table_name": table_name,
            "columns": columns,
            "kwargs": kwargs,
        })

    with patch.object(mod.op, "create_table", side_effect=fake_create_table), \
         patch.object(mod.op, "create_index", side_effect=fake_create_index):
        mod.upgrade()

    assert "person_preferences" in created_tables
    pp_elements = created_tables["person_preferences"]

    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    col_map = {elem.name: elem for elem in pp_elements if isinstance(elem, sa.Column)}
    constraints = [elem for elem in pp_elements if isinstance(elem, sa.UniqueConstraint)]

    expected_cols = {
        "id", "person_id", "reminders_after_signoff", "preferred_timezone",
        "business_id", "metadata", "created_at", "updated_at",
    }
    assert expected_cols.issubset(set(col_map.keys()))
    assert not col_map["person_id"].nullable
    assert not col_map["reminders_after_signoff"].nullable
    assert col_map["preferred_timezone"].nullable
    assert isinstance(col_map["metadata"].type, postgresql.JSONB)

    # Exactly one unique constraint named uq_person_preferences_person_id
    assert len(constraints) == 1
    assert constraints[0].name == "uq_person_preferences_person_id"
    constraint_col_names = [
        c.name if hasattr(c, "name") else str(c) for c in constraints[0].columns
    ] if constraints[0].columns else list(constraints[0]._pending_colargs)
    assert "person_id" in constraint_col_names

    # Check index on person_id
    pp_indexes = [idx for idx in created_indexes if idx["table_name"] == "person_preferences"]
    assert any(idx["name"] == "ix_person_preferences_person_id" for idx in pp_indexes)


def test_migration_downgrade_drops_all_objects_in_reverse_order():
    """Verify downgrade drops indexes and tables in safe reverse order."""
    mod = _load_migration_module()

    drop_log: list[tuple[str, str]] = []

    def fake_drop_index(name, **kwargs):
        drop_log.append(("drop_index", name))

    def fake_drop_table(name, **kwargs):
        drop_log.append(("drop_table", name))

    with patch.object(mod.op, "drop_index", side_effect=fake_drop_index), \
         patch.object(mod.op, "drop_table", side_effect=fake_drop_table):
        mod.downgrade()

    # person_preferences index then table dropped first
    pp_idx_pos = drop_log.index(("drop_index", "ix_person_preferences_person_id"))
    pp_table_pos = drop_log.index(("drop_table", "person_preferences"))
    assert pp_idx_pos < pp_table_pos

    # workday_sessions indexes dropped before table
    ws_indexes = [
        "uq_workday_sessions_active_person",
        "ix_workday_sessions_person_started_at",
        "ix_workday_sessions_person_work_date",
        "ix_workday_sessions_end_source_event_id",
        "ix_workday_sessions_start_source_event_id",
        "ix_workday_sessions_status",
        "ix_workday_sessions_work_date",
        "ix_workday_sessions_person_id",
    ]
    ws_table_pos = drop_log.index(("drop_table", "workday_sessions"))
    for idx_name in ws_indexes:
        pos = drop_log.index(("drop_index", idx_name))
        assert pos < ws_table_pos, f"Index {idx_name} was not dropped before workday_sessions table"


# ---------------------------------------------------------------------------
# 2. Safety Gate Registration Tests
# ---------------------------------------------------------------------------

def test_workday_lifecycle_modules_in_safety_gate():
    """Verify both repository modules are registered in ALL_SESSION_MODULES."""
    assert "infrastructure.database.workday_session_repository" in ALL_SESSION_MODULES
    assert "infrastructure.database.person_preference_repository" in ALL_SESSION_MODULES


def test_safety_gate_redirects_both_workday_lifecycle_repositories(monkeypatch):
    """Verify redirect_session_factories correctly redirects SessionLocal in both modules."""
    mock_staging_engine = MagicMock(name="mock_staging_engine")

    import infrastructure.database.workday_session_repository as ws_mod
    import infrastructure.database.person_preference_repository as pp_mod

    redirect_session_factories(mock_staging_engine, monkeypatch)

    assert ws_mod.SessionLocal.kw["bind"] is mock_staging_engine
    assert pp_mod.SessionLocal.kw["bind"] is mock_staging_engine


# ---------------------------------------------------------------------------
# 3. ApplicationContainer and Bootstrap Wiring Tests
# ---------------------------------------------------------------------------

def test_container_holds_workday_lifecycle_repositories():
    """Verify ApplicationContainer holds workday and person preference repositories with defaults."""
    # Test default None
    container_defaults = ApplicationContainer(
        engine=MagicMock(),
        knowledge_base_ingestion_service=MagicMock(),
        repository=MagicMock(),
        activity_service=MagicMock(),
        activity_processor=MagicMock(),
        activity_question_service=MagicMock(),
        meeting_transcript_service=MagicMock(),
        meeting_intelligence_service=MagicMock(),
        meeting_transcript_provider=MagicMock(),
        meeting_recording_provider=MagicMock(),
        teams_subscription_repository=MagicMock(),
        teams_subscription_service=MagicMock(),
        teams_recording_subscription_service=MagicMock(),
        reminder_repository=MagicMock(),
        reminder_service=MagicMock(),
    )
    assert container_defaults.workday_session_repository is None
    assert container_defaults.person_preference_repository is None

    # Test explicit injection
    mock_ws_repo = MagicMock(spec=WorkdaySessionRepository)
    mock_pp_repo = MagicMock(spec=PersonPreferenceRepository)

    container_injected = ApplicationContainer(
        engine=MagicMock(),
        knowledge_base_ingestion_service=MagicMock(),
        repository=MagicMock(),
        activity_service=MagicMock(),
        activity_processor=MagicMock(),
        activity_question_service=MagicMock(),
        meeting_transcript_service=MagicMock(),
        meeting_intelligence_service=MagicMock(),
        meeting_transcript_provider=MagicMock(),
        meeting_recording_provider=MagicMock(),
        teams_subscription_repository=MagicMock(),
        teams_subscription_service=MagicMock(),
        teams_recording_subscription_service=MagicMock(),
        reminder_repository=MagicMock(),
        reminder_service=MagicMock(),
        workday_session_repository=mock_ws_repo,
        person_preference_repository=mock_pp_repo,
    )
    assert container_injected.workday_session_repository is mock_ws_repo
    assert container_injected.person_preference_repository is mock_pp_repo


def test_bootstrap_instantiates_and_wires_both_repositories():
    """Verify bootstrap() constructs PostgreSQLWorkdaySessionRepository and PostgreSQLPersonPreferenceRepository."""
    from application.bootstrap.bootstrap import bootstrap

    with patch("application.bootstrap.bootstrap.PostgreSQLCalendarRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLGovernanceRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLCommunicationRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLActivityRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingTranscriptRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLTeamsSubscriptionRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLReminderRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOperationalItemRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOrganizationEventRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseDocumentRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseChunkRepository"), \
         patch("application.bootstrap.bootstrap.QdrantKnowledgeBaseRepository"), \
         patch("application.bootstrap.bootstrap.MinIOKnowledgeBaseStorage"), \
         patch("application.bootstrap.bootstrap.SlackClient") as mock_slack_cls, \
         patch("application.bootstrap.bootstrap.SlackIdentityService") as mock_identity_cls, \
         patch("application.bootstrap.bootstrap.MicrosoftGraphTokenProvider"), \
         patch("application.bootstrap.bootstrap.PostgreSQLWorkdaySessionRepository") as mock_ws_cls, \
         patch("application.bootstrap.bootstrap.PostgreSQLPersonPreferenceRepository") as mock_pp_cls:

        mock_slack_cls.return_value = MagicMock()
        mock_identity_cls.return_value = MagicMock()

        mock_ws_inst = MagicMock(spec=PostgreSQLWorkdaySessionRepository)
        mock_ws_cls.return_value = mock_ws_inst

        mock_pp_inst = MagicMock(spec=PostgreSQLPersonPreferenceRepository)
        mock_pp_cls.return_value = mock_pp_inst

        container = bootstrap()

        mock_ws_cls.assert_called_once_with()
        mock_pp_cls.assert_called_once_with()

        assert container.workday_session_repository is mock_ws_inst
        assert container.person_preference_repository is mock_pp_inst


def test_database_package_exports():
    """Verify infrastructure.database exports both repositories."""
    import infrastructure.database as db_pkg

    assert hasattr(db_pkg, "PostgreSQLWorkdaySessionRepository")
    assert hasattr(db_pkg, "PostgreSQLPersonPreferenceRepository")
    assert db_pkg.PostgreSQLWorkdaySessionRepository is PostgreSQLWorkdaySessionRepository
    assert db_pkg.PostgreSQLPersonPreferenceRepository is PostgreSQLPersonPreferenceRepository
    assert "PostgreSQLWorkdaySessionRepository" in db_pkg.__all__
    assert "PostgreSQLPersonPreferenceRepository" in db_pkg.__all__
