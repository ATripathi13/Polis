from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from domain.activity import (
    PersonPreference,
    SignoffReminderPolicy,
)
from domain.common.identifier import Identifier
from infrastructure.database import person_preference_repository as repo_module
from infrastructure.database.models import PersonPreferenceModel
from infrastructure.database.person_preference_repository import (
    PostgreSQLPersonPreferenceRepository,
)


def compile_filter(expr) -> str:
    """Compile a SQLAlchemy expression into a deterministic literal string."""
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def make_preference(
    person_id: str = "U100",
    policy: SignoffReminderPolicy | str = SignoffReminderPolicy.CONTINUE,
    preferred_timezone: str | None = None,
    business_id: str = "BIZ-PREF-1",
    metadata: dict | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> PersonPreference:
    return PersonPreference(
        identifier=Identifier(graph_id=uuid4(), business_id=business_id),
        person_id=person_id,
        reminders_after_signoff=policy,
        preferred_timezone=preferred_timezone,
        metadata=dict(metadata or {"notifications": "enabled"}),
        created_at=created_at or datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc),
        updated_at=updated_at or datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc),
    )


def make_preference_model(
    pref: PersonPreference | None = None,
    id_str: str | None = None,
    person_id: str = "U100",
    policy: str = "continue",
    preferred_timezone: str | None = None,
    business_id: str = "BIZ-PREF-1",
    metadata: dict | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> PersonPreferenceModel:
    if pref is not None:
        return PersonPreferenceModel(
            id=str(pref.identifier.graph_id),
            person_id=pref.person_id,
            reminders_after_signoff=pref.reminders_after_signoff.value,
            preferred_timezone=pref.preferred_timezone,
            business_id=pref.identifier.business_id,
            metadata_=dict(pref.metadata),
            created_at=pref.created_at,
            updated_at=pref.updated_at,
        )

    return PersonPreferenceModel(
        id=id_str or str(uuid4()),
        person_id=person_id,
        reminders_after_signoff=policy,
        preferred_timezone=preferred_timezone,
        business_id=business_id,
        metadata_=dict(metadata or {"notifications": "enabled"}),
        created_at=created_at or datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc),
        updated_at=updated_at or datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc),
    )


class FakeQuery:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.filters = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
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
# 1. Insert New Preference & Verify Complete ORM Fields
# =====================================================================


def test_save_new_preference_inserts_record_with_complete_orm_mapping():
    pref = make_preference(
        person_id="U100",
        policy=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY,
        preferred_timezone="America/New_York",
        business_id="BIZ-PREF-100",
        metadata={"channel": "slack", "tier": "premium"},
        created_at=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc),
    )

    session = FakeSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    repo.save(pref)

    assert len(session.added) == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True

    record = session.added[0]
    assert isinstance(record, PersonPreferenceModel)
    assert record.id == str(pref.identifier.graph_id)
    assert record.person_id == "U100"
    assert record.reminders_after_signoff == "pause_until_next_workday"
    assert record.preferred_timezone == "America/New_York"
    assert record.business_id == "BIZ-PREF-100"
    assert record.metadata_ == {"channel": "slack", "tier": "premium"}
    assert record.created_at == pref.created_at
    assert record.updated_at == pref.updated_at


# =====================================================================
# 2. Update Existing Preference in Place
# =====================================================================


def test_save_updates_existing_preference_in_place_without_duplicate():
    pref_initial = make_preference(
        person_id="U100",
        policy=SignoffReminderPolicy.CONTINUE,
        preferred_timezone=None,
    )
    existing_record = make_preference_model(pref=pref_initial)

    updated_time = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    pref_updated = PersonPreference(
        identifier=pref_initial.identifier,
        person_id="U100",
        reminders_after_signoff=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY,
        preferred_timezone="Asia/Tokyo",
        metadata={"channel": "slack", "updated": True},
        created_at=pref_initial.created_at,
        updated_at=updated_time,
    )

    session = FakeSession([existing_record])
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    repo.save(pref_updated)

    assert len(session.added) == 0  # Updated in place, no duplicate insert
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True

    assert existing_record.reminders_after_signoff == "pause_until_next_workday"
    assert existing_record.preferred_timezone == "Asia/Tokyo"
    assert existing_record.metadata_ == {"channel": "slack", "updated": True}
    assert existing_record.updated_at == updated_time


# =====================================================================
# 3. Domain Reconstitution & Identifier Round-Trip
# =====================================================================


def test_to_domain_restores_identifier_uuid_and_business_id():
    fixed_uuid = uuid4()
    record = make_preference_model(
        id_str=str(fixed_uuid),
        business_id="BUSINESS-PREF-999",
        person_id="U200",
        policy="pause_until_next_workday",
        preferred_timezone="Europe/London",
    )

    domain_pref = PostgreSQLPersonPreferenceRepository._to_domain(record)

    assert isinstance(domain_pref, PersonPreference)
    assert domain_pref.identifier.graph_id == fixed_uuid
    assert domain_pref.identifier.business_id == "BUSINESS-PREF-999"
    assert domain_pref.person_id == "U200"
    assert domain_pref.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert domain_pref.preferred_timezone == "Europe/London"


@pytest.mark.parametrize(
    ("policy_str", "expected_enum"),
    [
        ("continue", SignoffReminderPolicy.CONTINUE),
        ("pause_until_next_workday", SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY),
    ],
)
def test_policy_enum_round_trip(policy_str, expected_enum):
    record = make_preference_model(policy=policy_str)
    domain_pref = PostgreSQLPersonPreferenceRepository._to_domain(record)
    assert domain_pref.reminders_after_signoff == expected_enum


def test_preferred_timezone_and_none_handling():
    record_with_tz = make_preference_model(preferred_timezone="Asia/Kolkata")
    domain_with_tz = PostgreSQLPersonPreferenceRepository._to_domain(record_with_tz)
    assert domain_with_tz.preferred_timezone == "Asia/Kolkata"

    record_without_tz = make_preference_model(preferred_timezone=None)
    domain_without_tz = PostgreSQLPersonPreferenceRepository._to_domain(record_without_tz)
    assert domain_without_tz.preferred_timezone is None


def test_metadata_defensive_copying():
    original_meta = {"key": "original", "flags": [1, 2]}
    record = make_preference_model(metadata=original_meta)

    domain_pref = PostgreSQLPersonPreferenceRepository._to_domain(record)
    assert domain_pref.metadata == original_meta

    domain_pref.metadata["key"] = "mutated"
    assert record.metadata_["key"] == "original"

    session = FakeSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)
    repo.save(domain_pref)

    saved_record = session.added[0]
    domain_pref.metadata["key"] = "second_mutation"
    assert saved_record.metadata_["key"] == "mutated"


# =====================================================================
# 4. Query Behavior: find_by_person_id
# =====================================================================


def test_find_by_person_id_filters_exactly_and_does_not_commit():
    record = make_preference_model(person_id="U100", policy="pause_until_next_workday")
    session = FakeSession([record])
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    found = repo.find_by_person_id("U100")

    assert found is not None
    assert found.person_id == "U100"
    assert found.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert session.commits == 0
    assert session.closed is True

    compiled = [compile_filter(f) for f in session.query_instance.filters]
    assert "person_preferences.person_id = 'U100'" in compiled


def test_find_by_person_id_returns_none_when_missing():
    session = FakeSession([])
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    found = repo.find_by_person_id("U_MISSING")

    assert found is None
    assert session.commits == 0
    assert session.closed is True


# =====================================================================
# 5. Query Behavior: get_or_default Semantics
# =====================================================================


def test_get_or_default_returns_persisted_preference_when_present():
    record = make_preference_model(
        person_id="U100",
        policy="pause_until_next_workday",
        preferred_timezone="UTC",
    )
    session = FakeSession([record])
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    result = repo.get_or_default("U100")

    assert isinstance(result, PersonPreference)
    assert result.person_id == "U100"
    assert result.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert result.preferred_timezone == "UTC"
    assert session.commits == 0
    assert len(session.added) == 0
    assert session.closed is True


def test_get_or_default_returns_transient_default_when_missing():
    session = FakeSession([])
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    result = repo.get_or_default("U_MISSING")

    assert isinstance(result, PersonPreference)
    assert result.person_id == "U_MISSING"
    assert result.reminders_after_signoff == SignoffReminderPolicy.CONTINUE
    assert result.preferred_timezone is None
    # Crucial: Must NOT add to session or commit
    assert len(session.added) == 0
    assert session.commits == 0
    assert session.closed is True


# =====================================================================
# 6. Concurrency & Named Unique Constraint Error Handling
# =====================================================================


def test_save_named_unique_constraint_via_diag_rolls_back_and_raises_value_error():
    from types import SimpleNamespace

    diag = SimpleNamespace(constraint_name="uq_person_preferences_person_id")
    orig = SimpleNamespace(diag=diag)
    error = IntegrityError("duplicate key value", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)
    pref = make_preference(person_id="U100")

    with pytest.raises(
        ValueError,
        match="Preference for person 'U100' already exists or a concurrent write occurred",
    ):
        repo.save(pref)

    assert session.commits == 1
    assert session.rollbacks == 1
    assert session.closed is True


def test_save_named_unique_constraint_via_orig_rolls_back_and_raises_value_error():
    from types import SimpleNamespace

    orig = SimpleNamespace(constraint_name="uq_person_preferences_person_id")
    error = IntegrityError("duplicate key value", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)
    pref = make_preference(person_id="U200")

    with pytest.raises(
        ValueError,
        match="Preference for person 'U200' already exists or a concurrent write occurred",
    ):
        repo.save(pref)

    assert session.rollbacks == 1
    assert session.closed is True


def test_save_named_unique_constraint_via_message_fallback_rolls_back_and_raises_value_error():
    orig = Exception('violates unique constraint "uq_person_preferences_person_id"')
    error = IntegrityError("duplicate", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)
    pref = make_preference(person_id="U300")

    with pytest.raises(
        ValueError,
        match="Preference for person 'U300' already exists or a concurrent write occurred",
    ):
        repo.save(pref)

    assert session.rollbacks == 1
    assert session.closed is True


def test_save_unrelated_integrity_error_with_diag_rolls_back_and_is_reraised():
    from types import SimpleNamespace

    diag = SimpleNamespace(constraint_name="fk_some_other_table")
    orig = SimpleNamespace(diag=diag)
    error = IntegrityError("foreign key violation", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)
    pref = make_preference(person_id="U100")

    with pytest.raises(IntegrityError) as exc_info:
        repo.save(pref)

    assert exc_info.value is error
    assert session.commits == 1
    assert session.rollbacks == 1
    assert session.closed is True


def test_save_unrelated_integrity_error_with_unrelated_message_rolls_back_and_is_reraised():
    orig = Exception('duplicate key value violates unique constraint "uq_other_constraint"')
    error = IntegrityError("duplicate", {}, orig)

    class FailingSession(FakeSession):
        def commit(self):
            super().commit()
            raise error

    session = FailingSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)
    pref = make_preference(person_id="U100")

    with pytest.raises(IntegrityError) as exc_info:
        repo.save(pref)

    assert exc_info.value is error
    assert session.rollbacks == 1
    assert session.closed is True



# =====================================================================
# 7. Input Validation
# =====================================================================


def test_save_rejects_non_person_preference_instance():
    session = FakeSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    with pytest.raises(TypeError, match="preference must be an instance of PersonPreference"):
        repo.save("not-a-preference")  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_id", ["", "   ", None, 12345, []])
def test_queries_reject_invalid_person_id(invalid_id):
    session = FakeSession()
    repo = PostgreSQLPersonPreferenceRepository(session_factory=lambda: session)

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_by_person_id(invalid_id)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.get_or_default(invalid_id)  # type: ignore[arg-type]


# =====================================================================
# 8. Default SessionLocal Resolution via Module Monkeypatching
# =====================================================================


def test_default_session_local_used_when_session_factory_omitted(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(repo_module, "SessionLocal", lambda: session)

    repo = PostgreSQLPersonPreferenceRepository()
    pref = make_preference(person_id="U100")

    repo.save(pref)

    assert len(session.added) == 1
    assert session.commits == 1
    assert session.closed is True
