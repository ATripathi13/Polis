"""
Unit tests for InMemoryPersonPreferenceRepository.
"""

import pytest

from domain.activity import (
    InMemoryPersonPreferenceRepository,
    PersonPreference,
    SignoffReminderPolicy,
)


# =====================================================================
# 1. Insert, Update, and Lookup
# =====================================================================


def test_save_and_find_by_person_id():
    repo = InMemoryPersonPreferenceRepository()
    pref = PersonPreference.create(
        person_id="U100",
        reminders_after_signoff=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY,
        preferred_timezone="Asia/Kolkata",
    )

    repo.save(pref)

    found = repo.find_by_person_id("U100")
    assert found is not None
    assert found.person_id == "U100"
    assert found.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert found.preferred_timezone == "Asia/Kolkata"


def test_save_updates_existing_preference():
    repo = InMemoryPersonPreferenceRepository()
    pref = PersonPreference.create(person_id="U100")
    repo.save(pref)

    pref.update_reminders_after_signoff(SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY)
    pref.update_preferred_timezone("America/New_York")
    repo.save(pref)

    found = repo.find_by_person_id("U100")
    assert found is not None
    assert found.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert found.preferred_timezone == "America/New_York"


def test_find_by_person_id_returns_none_when_missing():
    repo = InMemoryPersonPreferenceRepository()
    assert repo.find_by_person_id("U_NON_EXISTENT") is None


def test_different_people_do_not_conflict():
    repo = InMemoryPersonPreferenceRepository()
    pref1 = PersonPreference.create(
        person_id="U100",
        reminders_after_signoff=SignoffReminderPolicy.CONTINUE,
    )
    pref2 = PersonPreference.create(
        person_id="U200",
        reminders_after_signoff=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY,
    )

    repo.save(pref1)
    repo.save(pref2)

    assert repo.find_by_person_id("U100").reminders_after_signoff == SignoffReminderPolicy.CONTINUE
    assert repo.find_by_person_id("U200").reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY


# =====================================================================
# 2. get_or_default() Semantics
# =====================================================================


def test_get_or_default_returns_persisted_preference():
    repo = InMemoryPersonPreferenceRepository()
    saved = PersonPreference.create(
        person_id="U100",
        reminders_after_signoff=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY,
        preferred_timezone="UTC",
    )
    repo.save(saved)

    result = repo.get_or_default("U100")

    assert result is saved
    assert result.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert result.preferred_timezone == "UTC"


def test_get_or_default_returns_transient_default_when_missing():
    repo = InMemoryPersonPreferenceRepository()

    result = repo.get_or_default("U_MISSING")

    assert isinstance(result, PersonPreference)
    assert result.person_id == "U_MISSING"
    assert result.reminders_after_signoff == SignoffReminderPolicy.CONTINUE
    assert result.preferred_timezone is None


def test_get_or_default_does_not_mutate_storage_when_missing():
    repo = InMemoryPersonPreferenceRepository()

    _ = repo.get_or_default("U_MISSING")

    # Critical: storage must remain clean and unmutated
    assert repo.find_by_person_id("U_MISSING") is None
    assert "U_MISSING" not in repo._preferences


# =====================================================================
# 3. Validation on Invalid person_id
# =====================================================================


@pytest.mark.parametrize("invalid_id", ["", "   ", None, 123, []])
def test_rejects_invalid_person_id_on_queries(invalid_id):
    repo = InMemoryPersonPreferenceRepository()

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.find_by_person_id(invalid_id)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        repo.get_or_default(invalid_id)  # type: ignore[arg-type]
