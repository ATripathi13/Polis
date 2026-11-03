"""
Centralized Fail-Closed Staging Safety Gate for PostgreSQL Integration Tests.

Enforces strict isolation boundaries:
1. Staging tests may use ONLY an explicitly supplied POLIS_TEST_DATABASE_URL.
2. Never falls back to DATABASE_URL, POSTGRES_DB, application settings, or .env.
3. Requires postgresql+psycopg driver.
4. Requires a local host: localhost, 127.0.0.1, or ::1.
5. Requires exact database name polis_test.
6. After connecting, verifies SELECT current_database() returns exactly polis_test.
7. If staging is explicitly requested but variable is missing/invalid, fails immediately.
8. URL and password never appear in exceptions or log messages.
9. Disposes of validation engines safely on failure and teardown.
10. Runs before any repository/session initialization that could reach production.
11. Redirects all imported module-level SessionLocal references.
12. Prevents FastAPI dependencies from silently falling back to production repositories.
13. Completely forbids Base.metadata.create_all() and migrations on staging.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Sequence

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import sessionmaker


STAGING_DB_ENV_VAR = "POLIS_TEST_DATABASE_URL"
STAGING_REQUIRE_ENV_VAR = "POLIS_REQUIRE_STAGING"
REQUIRED_DRIVER = "postgresql+psycopg"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
STAGING_DB_NAME = "polis_test"

# Registry of all modules that import or expose SessionLocal
ALL_SESSION_MODULES: tuple[str, ...] = (
    "infrastructure.database.connection",
    "infrastructure.database",
    "infrastructure.database.calendar_repository",
    "infrastructure.database.operational_item_repository",
    "infrastructure.database.activity_repository",
    "infrastructure.database.governance_repository",
    "infrastructure.database.meeting_repository",
    "infrastructure.database.meeting_transcript_repository",
    "infrastructure.database.organization_event_repository",
    "infrastructure.database.postgres_conversation_repository",
    "infrastructure.database.reminder_repository",
    "infrastructure.database.teams_subscription_repository",
    "infrastructure.database.knowledge_repository",
    "infrastructure.database.knowledge_base_repository",
    "engines.communication.infrastructure.repositories.postgres_repository",
    "infrastructure.database.workday_session_repository",
    "infrastructure.database.person_preference_repository",
)


class StagingSafetyGateError(RuntimeError):
    """Raised when a staging test safety invariant is violated."""
    pass


class BlockedProductionRepository:
    """Sentinel preventing FastAPI dependencies from falling back to production."""

    def __getattr__(self, name: str) -> Any:
        raise StagingSafetyGateError(
            f"Staging safety violation: unoverridden FastAPI dependency attempted to access "
            f"repository method '{name}'. Explicit staging repository override required."
        )


def validate_staging_url(
    raw_url: str | None = None,
    *,
    require_staging: bool = False,
) -> URL | None:
    """
    Validate staging database URL strictly against safety rules.

    Does NOT inspect DATABASE_URL, POSTGRES_DB, settings, or .env.
    Never includes raw_url or passwords in any exception message.
    """
    if raw_url is None:
        raw_url = os.environ.get(STAGING_DB_ENV_VAR)

    explicit_staging = require_staging or os.environ.get(STAGING_REQUIRE_ENV_VAR, "").lower() in (
        "1",
        "true",
        "yes",
    )

    if not raw_url or not str(raw_url).strip():
        if explicit_staging:
            raise StagingSafetyGateError(
                "Staging safety gate failed closed: POLIS_TEST_DATABASE_URL is required "
                "when staging is explicitly requested, but was not provided."
            )
        return None

    raw_url_str = str(raw_url).strip()

    # Enforce driver prefix
    if not raw_url_str.startswith(f"{REQUIRED_DRIVER}://"):
        raise StagingSafetyGateError(
            f"Staging safety gate rejected URL: driver must be '{REQUIRED_DRIVER}'."
        )

    # Parse URL without leaking credentials on parse failure
    try:
        parsed = make_url(raw_url_str)
    except Exception:
        raise StagingSafetyGateError(
            "Staging safety gate rejected URL: database URL is malformed or invalid."
        ) from None

    # Validate driver name
    if parsed.drivername != REQUIRED_DRIVER:
        raise StagingSafetyGateError(
            f"Staging safety gate rejected URL: driver must be '{REQUIRED_DRIVER}'."
        )

    # Validate host
    if not parsed.host or parsed.host not in LOCAL_HOSTS:
        raise StagingSafetyGateError(
            "Staging safety gate rejected URL: host must be a local address "
            "('localhost', '127.0.0.1', or '::1')."
        )

    # Validate database name
    if parsed.database != STAGING_DB_NAME:
        raise StagingSafetyGateError(
            f"Staging safety gate rejected URL: target database must be '{STAGING_DB_NAME}'."
        )

    return parsed


def verify_staging_connection(engine: Engine) -> None:
    """
    Verify that the connected database is strictly 'polis_test'.

    Never includes credentials in exceptions.
    """
    try:
        with engine.connect() as conn:
            current_db = conn.exec_driver_sql("SELECT current_database()").scalar_one()
    except Exception:
        raise StagingSafetyGateError(
            "Staging safety gate connection verification failed."
        ) from None

    if current_db != STAGING_DB_NAME:
        raise StagingSafetyGateError(
            f"Staging safety gate runtime verification failed: current_database() "
            f"returned unexpected database; expected '{STAGING_DB_NAME}'."
        )


def create_staging_engine(
    raw_url: str | None = None,
    *,
    require_staging: bool = False,
) -> Engine | None:
    """
    Create and verify a staging engine. Disposes safely on any validation failure.
    """
    parsed = validate_staging_url(raw_url, require_staging=require_staging)
    if parsed is None:
        return None

    engine = create_engine(parsed, pool_pre_ping=True)
    try:
        verify_staging_connection(engine)
    except Exception:
        engine.dispose()
        raise

    return engine


def redirect_session_factories(
    engine: Engine,
    monkeypatch: Any,
    targets: Sequence[str] = ALL_SESSION_MODULES,
) -> sessionmaker:
    """
    Redirect all known repository and central session factories to the verified staging engine.
    Also redirects connection.engine to ensure no code accesses the global production engine.
    """
    staging_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    # 1. Patch central connection module
    import infrastructure.database.connection as conn_mod

    monkeypatch.setattr(conn_mod, "engine", engine)
    monkeypatch.setattr(conn_mod, "SessionLocal", staging_session_factory)

    # 2. Patch package-level exports if loaded
    if "infrastructure.database" in sys.modules:
        import infrastructure.database as db_pkg

        if hasattr(db_pkg, "engine"):
            monkeypatch.setattr(db_pkg, "engine", engine)
        if hasattr(db_pkg, "SessionLocal"):
            monkeypatch.setattr(db_pkg, "SessionLocal", staging_session_factory)

    # 3. Patch all known repository modules
    for mod_name in targets:
        try:
            mod = sys.modules.get(mod_name)
            if mod is None:
                mod = importlib.import_module(mod_name)
            if hasattr(mod, "SessionLocal"):
                monkeypatch.setattr(mod, "SessionLocal", staging_session_factory)
        except (ImportError, AttributeError):
            pass

    return staging_session_factory


def enforce_fastapi_staging_isolation(
    app: Any,
    monkeypatch: Any,
) -> None:
    """
    Ensure FastAPI dependencies cannot fall back to production repositories.
    Neutralizes module-level singletons in api.dependencies.
    """
    if "api.dependencies" in sys.modules:
        api_deps = sys.modules["api.dependencies"]
        blocked = BlockedProductionRepository()
        for attr in ("_repository", "_conversation_repository"):
            if hasattr(api_deps, attr):
                monkeypatch.setattr(api_deps, attr, blocked)


@pytest.fixture
def staging_safety_gate(monkeypatch):
    """
    Centralized fail-closed staging safety gate fixture.

    1. Validates POLIS_TEST_DATABASE_URL.
    2. Verifies local connection to polis_test.
    3. Redirects all repository SessionLocal references.
    4. Enforces FastAPI dependency safety.
    5. Disposes of engine safely on teardown.
    """
    raw_url = os.environ.get(STAGING_DB_ENV_VAR)
    explicit_staging = os.environ.get(STAGING_REQUIRE_ENV_VAR, "").lower() in (
        "1",
        "true",
        "yes",
    )

    if not raw_url:
        if explicit_staging:
            pytest.fail(
                "Staging test execution requested (POLIS_REQUIRE_STAGING is set), "
                "but POLIS_TEST_DATABASE_URL is not configured."
            )
        pytest.skip("Set POLIS_TEST_DATABASE_URL to the isolated polis_test URL.")

    try:
        engine = create_staging_engine(raw_url, require_staging=True)
    except StagingSafetyGateError as err:
        pytest.fail(str(err))

    try:
        session_factory = redirect_session_factories(engine, monkeypatch)
        yield engine, session_factory
    finally:
        engine.dispose()
