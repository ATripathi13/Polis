"""
Offline Unit Tests for Centralized Staging Safety Gate.

Validates all safety invariants using mocked engines, session factories, and environment variables.
DO NOT CONNECT TO POSTGRESQL.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from tests.staging_safety_gate import (
    ALL_SESSION_MODULES,
    BlockedProductionRepository,
    REQUIRED_DRIVER,
    STAGING_DB_NAME,
    StagingSafetyGateError,
    create_staging_engine,
    enforce_fastapi_staging_isolation,
    redirect_session_factories,
    validate_staging_url,
    verify_staging_connection,
)


def test_missing_staging_url_fails_closed_when_staging_explicitly_selected(monkeypatch):
    """Missing staging URL must fail closed when staging run is explicitly required."""
    monkeypatch.delenv("POLIS_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("POLIS_REQUIRE_STAGING", "1")

    with pytest.raises(StagingSafetyGateError, match="failed closed"):
        validate_staging_url(None)

    with pytest.raises(StagingSafetyGateError, match="failed closed"):
        validate_staging_url("", require_staging=True)

    with pytest.raises(StagingSafetyGateError, match="failed closed"):
        validate_staging_url("   ", require_staging=True)


def test_missing_staging_url_skips_when_staging_not_required(monkeypatch):
    """Missing staging URL returns None when staging is not explicitly required."""
    monkeypatch.delenv("POLIS_TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("POLIS_REQUIRE_STAGING", raising=False)

    result = validate_staging_url(None, require_staging=False)
    assert result is None


def test_malformed_staging_url_rejected_without_credential_leak():
    """Malformed database URL must be rejected without exposing credentials."""
    username = "sensitive_user"
    secret = "super_secret_cleartext_password_123"
    malformed_url = f"postgresql+psycopg://{username}:{secret}@localhost:invalid_port/polis_test"

    with pytest.raises(StagingSafetyGateError) as exc_info:
        validate_staging_url(malformed_url, require_staging=True)

    err_msg = str(exc_info.value)
    err_repr = repr(exc_info.value)
    assert "malformed or invalid" in err_msg
    assert secret not in err_msg
    assert secret not in err_repr
    assert username not in err_msg
    assert username not in err_repr


def test_wrong_driver_rejected():
    """Any driver other than postgresql+psycopg must be rejected."""
    invalid_driver_urls = [
        "postgresql://user:pass@localhost:5432/polis_test",
        "sqlite:///polis_test.db",
        "mysql+pymysql://user:pass@localhost:5432/polis_test",
        "postgresql+asyncpg://user:pass@localhost:5432/polis_test",
    ]

    for url in invalid_driver_urls:
        with pytest.raises(StagingSafetyGateError, match="driver must be 'postgresql\\+psycopg'"):
            validate_staging_url(url, require_staging=True)


def test_non_local_host_rejected():
    """Non-local hosts must be strictly rejected."""
    secret = "remote_host_pass_999"
    non_local_urls = [
        f"postgresql+psycopg://user:{secret}@192.168.1.50:5432/polis_test",
        f"postgresql+psycopg://user:{secret}@database.aws.amazon.com:5432/polis_test",
        f"postgresql+psycopg://user:{secret}@10.0.0.1:5432/polis_test",
        f"postgresql+psycopg://user:{secret}@ctmc-vps.internal:5432/polis_test",
    ]

    for url in non_local_urls:
        with pytest.raises(StagingSafetyGateError) as exc_info:
            validate_staging_url(url, require_staging=True)

        err_msg = str(exc_info.value)
        assert "host must be a local address" in err_msg
        assert secret not in err_msg


def test_valid_local_hosts_accepted():
    """Local hosts localhost, 127.0.0.1, and ::1 must be accepted."""
    valid_urls = [
        "postgresql+psycopg://user:pass@localhost:5432/polis_test",
        "postgresql+psycopg://user:pass@127.0.0.1:5432/polis_test",
        "postgresql+psycopg://user:pass@[::1]:5432/polis_test",
    ]

    for url in valid_urls:
        parsed = validate_staging_url(url, require_staging=True)
        assert parsed is not None
        assert parsed.drivername == REQUIRED_DRIVER
        assert parsed.database == STAGING_DB_NAME


def test_wrong_database_name_rejected():
    """Target database must be strictly polis_test."""
    secret = "db_name_pass_888"
    wrong_db_urls = [
        f"postgresql+psycopg://user:{secret}@localhost:5432/ctmc_production",
        f"postgresql+psycopg://user:{secret}@localhost:5432/postgres",
        f"postgresql+psycopg://user:{secret}@localhost:5432/polis",
        f"postgresql+psycopg://user:{secret}@localhost:5432/test_db",
    ]

    for url in wrong_db_urls:
        with pytest.raises(StagingSafetyGateError) as exc_info:
            validate_staging_url(url, require_staging=True)

        err_msg = str(exc_info.value)
        assert "target database must be 'polis_test'" in err_msg
        assert secret not in err_msg


def test_current_database_mismatch_rejected_and_engine_disposed():
    """Runtime SELECT current_database() mismatch must be rejected and engine disposed."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.scalar_one.return_value = "ctmc_production"
    mock_conn.exec_driver_sql.return_value = mock_cursor
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    # 1. verify_staging_connection detects mismatch
    with pytest.raises(StagingSafetyGateError, match="current_database\\(\\) returned unexpected database"):
        verify_staging_connection(mock_engine)

    # 2. create_staging_engine disposes engine on mismatch
    with patch("tests.staging_safety_gate.create_engine", return_value=mock_engine):
        with pytest.raises(StagingSafetyGateError):
            create_staging_engine(
                "postgresql+psycopg://user:pass@localhost:5432/polis_test",
                require_staging=True,
            )

    mock_engine.dispose.assert_called_once()


def test_current_database_match_succeeds():
    """Runtime SELECT current_database() == 'polis_test' succeeds."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.scalar_one.return_value = "polis_test"
    mock_conn.exec_driver_sql.return_value = mock_cursor
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    # Must complete without error
    verify_staging_connection(mock_engine)


def test_url_and_password_never_appear_in_error_messages():
    """Passwords and raw URLs must never be leaked across all validation branches."""
    sensitive_token = "SUPER_SECRET_TOKEN_DO_NOT_LEAK"
    test_cases = [
        f"postgresql+psycopg://admin:{sensitive_token}@localhost:5432/ctmc_production",
        f"postgresql+psycopg://admin:{sensitive_token}@192.168.1.1:5432/polis_test",
        f"postgresql://admin:{sensitive_token}@localhost:5432/polis_test",
        f"postgresql+psycopg://admin:{sensitive_token}@localhost:5432/invalid[url",
    ]

    for url in test_cases:
        try:
            validate_staging_url(url, require_staging=True)
        except StagingSafetyGateError as err:
            assert sensitive_token not in str(err)
            assert sensitive_token not in repr(err)


def test_no_fallback_to_production_database_url_or_settings(monkeypatch):
    """Guard must never fall back to DATABASE_URL, POSTGRES_DB, or settings."""
    prod_secret = "prod_password_must_never_be_touched"
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://ctmc_user:{prod_secret}@remote-host:5432/ctmc_production")
    monkeypatch.setenv("POSTGRES_DB", "ctmc_production")
    monkeypatch.delenv("POLIS_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("POLIS_REQUIRE_STAGING", "1")

    # When staging is required but POLIS_TEST_DATABASE_URL is unset, it must fail closed
    with pytest.raises(StagingSafetyGateError, match="failed closed"):
        validate_staging_url(None)

    assert prod_secret not in os.environ.get("POLIS_TEST_DATABASE_URL", "")


def test_all_imported_session_factory_references_redirected(monkeypatch):
    """All known session factory references must be redirected to staging engine."""
    mock_staging_engine = MagicMock(name="staging_engine")

    # Redirect session factories
    session_factory = redirect_session_factories(mock_staging_engine, monkeypatch)

    assert session_factory.kw["bind"] is mock_staging_engine

    # Check connection module
    import infrastructure.database.connection as conn_mod
    assert conn_mod.engine is mock_staging_engine
    assert conn_mod.SessionLocal.kw["bind"] is mock_staging_engine

    # Check all registered modules that are loaded
    import sys
    for mod_name in ALL_SESSION_MODULES:
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            if hasattr(mod, "SessionLocal"):
                assert mod.SessionLocal.kw["bind"] is mock_staging_engine


def test_fastapi_dependencies_cannot_fallback_to_production_repository(monkeypatch):
    """FastAPI dependencies must not silently fall back to unoverridden production singletons."""
    mock_app = MagicMock()
    mock_session_factory = MagicMock()

    # Pre-populate mock api.dependencies if not imported
    mock_api_deps = MagicMock()
    mock_api_deps._repository = MagicMock()
    mock_api_deps._conversation_repository = MagicMock()

    with patch.dict("sys.modules", {"api.dependencies": mock_api_deps}):
        enforce_fastapi_staging_isolation(mock_app, monkeypatch)

        # The singletons must be replaced with BlockedProductionRepository
        assert isinstance(mock_api_deps._repository, BlockedProductionRepository)
        assert isinstance(mock_api_deps._conversation_repository, BlockedProductionRepository)

        # Invoking any method on unoverridden repository must fail closed
        with pytest.raises(StagingSafetyGateError, match="unoverridden FastAPI dependency"):
            mock_api_deps._repository.save(None)

        with pytest.raises(StagingSafetyGateError, match="unoverridden FastAPI dependency"):
            mock_api_deps._conversation_repository.save_message(None)


def test_no_create_all_or_migration_called_by_staging_path():
    """Verify that Base.metadata.create_all is not invoked by the staging safety gate."""
    with patch("infrastructure.database.models.Base.metadata.create_all") as mock_create_all:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.scalar_one.return_value = "polis_test"
        mock_conn.exec_driver_sql.return_value = mock_cursor
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("tests.staging_safety_gate.create_engine", return_value=mock_engine):
            engine = create_staging_engine(
                "postgresql+psycopg://user:pass@localhost:5432/polis_test",
                require_staging=True,
            )
            assert engine is mock_engine

        mock_create_all.assert_not_called()


def test_workday_lifecycle_repositories_registered_and_redirected(monkeypatch):
    """Verify workday session and person preference repositories are in ALL_SESSION_MODULES and redirected."""
    assert "infrastructure.database.workday_session_repository" in ALL_SESSION_MODULES
    assert "infrastructure.database.person_preference_repository" in ALL_SESSION_MODULES

    import infrastructure.database.person_preference_repository as pp_mod
    import infrastructure.database.workday_session_repository as ws_mod

    mock_staging_engine = MagicMock(name="staging_engine")
    redirect_session_factories(mock_staging_engine, monkeypatch)

    assert ws_mod.SessionLocal.kw["bind"] is mock_staging_engine
    assert pp_mod.SessionLocal.kw["bind"] is mock_staging_engine
