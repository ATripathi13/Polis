"""
Unit tests for the PersonPreference domain aggregate and SignoffReminderPolicy enum.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from domain.activity import PersonPreference, SignoffReminderPolicy
from domain.common.identifier import Identifier


# =====================================================================
# 1. Factory and Initialization
# =====================================================================


def test_create_default_preference():
    pref = PersonPreference.create(person_id="U12345")

    assert pref.person_id == "U12345"
    assert pref.reminders_after_signoff == SignoffReminderPolicy.CONTINUE
    assert pref.preferred_timezone is None
    assert pref.business_id == ""
    assert pref.metadata == {}
    assert isinstance(pref.graph_id, UUID)
    assert pref.state == "ACTIVE"


def test_create_with_explicit_business_id_and_metadata():
    metadata = {"slack_team_id": "T999", "tier": "gold"}
    pref = PersonPreference.create(
        person_id="U12345",
        business_id="pref-custom-001",
        metadata=metadata,
    )

    assert pref.person_id == "U12345"
    assert pref.business_id == "pref-custom-001"
    assert pref.metadata == metadata
    assert pref.metadata is not metadata  # Defensively copied


def test_create_with_explicit_enum_and_valid_timezone():
    pref = PersonPreference.create(
        person_id="U12345",
        reminders_after_signoff=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY,
        preferred_timezone="Asia/Kolkata",
    )

    assert pref.person_id == "U12345"
    assert pref.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert pref.preferred_timezone == "Asia/Kolkata"


def test_direct_constructor_with_identifier_and_timestamps():
    ident = Identifier(business_id="explicit-pref-id")
    created = datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc)
    updated = datetime(2026, 11, 2, 8, 45, tzinfo=timezone.utc)

    pref = PersonPreference(
        identifier=ident,
        person_id="U12345",
        reminders_after_signoff=SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY,
        preferred_timezone="America/New_York",
        metadata={"role": "engineer"},
        created_at=created,
        updated_at=updated,
    )

    assert pref.identifier == ident
    assert pref.business_id == "explicit-pref-id"
    assert pref.person_id == "U12345"
    assert pref.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert pref.preferred_timezone == "America/New_York"
    assert pref.created_at == created
    assert pref.updated_at == updated


def test_generated_timestamps_are_timezone_aware_utc():
    before = datetime.now(timezone.utc)
    pref = PersonPreference.create(person_id="U12345")
    after = datetime.now(timezone.utc)

    assert pref.created_at.tzinfo is not None
    assert pref.created_at.tzinfo == timezone.utc
    assert pref.updated_at.tzinfo is not None
    assert pref.updated_at.tzinfo == timezone.utc
    assert before <= pref.created_at <= after
    assert before <= pref.updated_at <= after


def test_entity_identity_and_equality():
    ident = Identifier(business_id="same-pref")
    pref1 = PersonPreference(identifier=ident, person_id="U1")
    pref2 = PersonPreference(identifier=ident, person_id="U2")
    pref3 = PersonPreference.create(person_id="U1")

    assert pref1 == pref2
    assert hash(pref1) == hash(pref2)
    assert pref1 != pref3
    assert pref1 != "not-an-entity"
    assert pref1 != 123


def test_entity_lifecycle_and_domain_events():
    pref = PersonPreference.create(person_id="U12345")
    assert pref.deleted_at is None

    pref.mark_deleted()
    assert pref.deleted_at is not None
    assert pref.deleted_at.tzinfo == timezone.utc

    pref.add_domain_event({"type": "preference_updated", "person_id": "U12345"})
    events = pref.pull_domain_events()
    assert len(events) == 1
    assert events[0]["type"] == "preference_updated"
    assert len(pref.pull_domain_events()) == 0


def test_signoff_reminder_policy_enum_definition():
    assert issubclass(SignoffReminderPolicy, str)
    assert SignoffReminderPolicy.CONTINUE == "continue"
    assert SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY == "pause_until_next_workday"
    assert SignoffReminderPolicy.CONTINUE.value == "continue"
    assert SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY.value == "pause_until_next_workday"


# =====================================================================
# 2. Validation
# =====================================================================


@pytest.mark.parametrize("blank_id", ["", "   ", None])
def test_rejects_blank_or_none_person_id(blank_id):
    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        PersonPreference.create(person_id=blank_id)


def test_rejects_falsy_non_string_person_id():
    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        PersonPreference.create(person_id=[])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "truthy_non_string",
    [
        12345,
        99.9,
        object(),
        {"key": "val"},
        ("tuple", 1),
    ],
)
def test_truthy_non_string_person_id_raises_value_error(truthy_non_string):
    with pytest.raises(ValueError, match="person_id must be a non-empty string"):
        PersonPreference.create(person_id=truthy_non_string)  # type: ignore[arg-type]


def test_preferred_timezone_accepts_none():
    pref = PersonPreference.create(person_id="U12345", preferred_timezone=None)
    assert pref.preferred_timezone is None


@pytest.mark.parametrize("blank_tz", ["", "   "])
def test_rejects_empty_or_whitespace_preferred_timezone(blank_tz):
    with pytest.raises(ValueError, match="preferred_timezone cannot be an empty string"):
        PersonPreference.create(person_id="U12345", preferred_timezone=blank_tz)


@pytest.mark.parametrize("non_string_tz", [123, True, [], {}])
def test_rejects_non_string_preferred_timezone(non_string_tz):
    with pytest.raises(ValueError, match="preferred_timezone cannot be an empty string"):
        PersonPreference.create(
            person_id="U12345",
            preferred_timezone=non_string_tz,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "invalid_tz",
    [
        "Mars/Olympus",
        "Invalid/Timezone",
        "America/NonExistentCity",
        "random-string",
    ],
)
def test_rejects_invalid_iana_timezone(invalid_tz):
    with pytest.raises(ValueError, match=f"Invalid timezone: {invalid_tz}"):
        PersonPreference.create(person_id="U12345", preferred_timezone=invalid_tz)


@pytest.mark.parametrize(
    "valid_tz",
    [
        "UTC",
        "Asia/Kolkata",
        "America/New_York",
        "Europe/London",
        "Australia/Sydney",
    ],
)
def test_accepts_valid_iana_timezones(valid_tz):
    pref = PersonPreference.create(person_id="U12345", preferred_timezone=valid_tz)
    assert pref.preferred_timezone == valid_tz


def test_preferred_timezone_strips_surrounding_whitespace():
    pref = PersonPreference.create(
        person_id="U12345",
        preferred_timezone="  Asia/Kolkata  ",
    )
    assert pref.preferred_timezone == "Asia/Kolkata"


@pytest.mark.parametrize(
    "invalid_policy",
    [
        "never",
        "pause",
        "stop",
        "unknown_policy",
        "",
        "   ",
    ],
)
def test_rejects_invalid_policy_string(invalid_policy):
    with pytest.raises(ValueError, match="Invalid SignoffReminderPolicy"):
        PersonPreference.create(
            person_id="U12345",
            reminders_after_signoff=invalid_policy,
        )


@pytest.mark.parametrize("unsupported_type", [None, 123, True, [], {}])
def test_rejects_unsupported_policy_types(unsupported_type):
    with pytest.raises(ValueError, match="Unsupported type for SignoffReminderPolicy"):
        PersonPreference.create(
            person_id="U12345",
            reminders_after_signoff=unsupported_type,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("raw_string", "expected_enum"),
    [
        ("continue", SignoffReminderPolicy.CONTINUE),
        ("CONTINUE", SignoffReminderPolicy.CONTINUE),
        ("Continue", SignoffReminderPolicy.CONTINUE),
        ("CoNtInUe", SignoffReminderPolicy.CONTINUE),
        ("pause_until_next_workday", SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY),
        ("PAUSE_UNTIL_NEXT_WORKDAY", SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY),
        ("Pause_Until_Next_Workday", SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY),
    ],
)
def test_case_insensitive_valid_policy_strings(raw_string, expected_enum):
    pref = PersonPreference.create(
        person_id="U12345",
        reminders_after_signoff=raw_string,
    )
    assert pref.reminders_after_signoff is expected_enum
    assert isinstance(pref.reminders_after_signoff, SignoffReminderPolicy)


def test_stored_policies_are_always_enum_members():
    pref_from_enum = PersonPreference.create(
        person_id="U1",
        reminders_after_signoff=SignoffReminderPolicy.CONTINUE,
    )
    pref_from_str = PersonPreference.create(
        person_id="U2",
        reminders_after_signoff="continue",
    )

    assert isinstance(pref_from_enum.reminders_after_signoff, SignoffReminderPolicy)
    assert isinstance(pref_from_str.reminders_after_signoff, SignoffReminderPolicy)
    assert pref_from_enum.reminders_after_signoff is SignoffReminderPolicy.CONTINUE
    assert pref_from_str.reminders_after_signoff is SignoffReminderPolicy.CONTINUE


# =====================================================================
# 3. update_reminders_after_signoff()
# =====================================================================


def test_update_reminders_after_signoff_successful_enum():
    past = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    pref = PersonPreference(
        person_id="U12345",
        reminders_after_signoff=SignoffReminderPolicy.CONTINUE,
        updated_at=past,
    )

    pref.update_reminders_after_signoff(SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY)

    assert pref.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert pref.updated_at > past


def test_update_reminders_after_signoff_successful_string():
    pref = PersonPreference.create(
        person_id="U12345",
        reminders_after_signoff=SignoffReminderPolicy.CONTINUE,
    )

    pref.update_reminders_after_signoff("PAUSE_UNTIL_NEXT_WORKDAY")

    assert pref.reminders_after_signoff == SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    assert isinstance(pref.reminders_after_signoff, SignoffReminderPolicy)


def test_update_reminders_after_signoff_advances_updated_at():
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    pref = PersonPreference(person_id="U12345", updated_at=past)

    pref.update_reminders_after_signoff(SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY)

    assert pref.updated_at > past


@pytest.mark.parametrize("invalid_update", ["invalid", "", 123, None, []])
def test_invalid_policy_update_leaves_policy_and_updated_at_unchanged(invalid_update):
    past = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    pref = PersonPreference(
        person_id="U12345",
        reminders_after_signoff=SignoffReminderPolicy.CONTINUE,
        updated_at=past,
    )

    with pytest.raises(ValueError):
        pref.update_reminders_after_signoff(invalid_update)  # type: ignore[arg-type]

    assert pref.reminders_after_signoff == SignoffReminderPolicy.CONTINUE
    assert pref.updated_at == past


# =====================================================================
# 4. update_preferred_timezone()
# =====================================================================


def test_update_preferred_timezone_successful():
    past = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    pref = PersonPreference(person_id="U12345", updated_at=past)

    pref.update_preferred_timezone("America/New_York")

    assert pref.preferred_timezone == "America/New_York"
    assert pref.updated_at > past


def test_update_preferred_timezone_clearing_with_none():
    past = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    pref = PersonPreference(
        person_id="U12345",
        preferred_timezone="Asia/Kolkata",
        updated_at=past,
    )

    pref.update_preferred_timezone(None)

    assert pref.preferred_timezone is None
    assert pref.updated_at > past


def test_update_preferred_timezone_advances_updated_at():
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    pref = PersonPreference(person_id="U12345", updated_at=past)

    pref.update_preferred_timezone("UTC")

    assert pref.updated_at > past


@pytest.mark.parametrize(
    "invalid_tz",
    [
        "",
        "   ",
        "Mars/Olympus",
        "Invalid/Timezone",
        123,
        True,
        [],
    ],
)
def test_invalid_timezone_update_leaves_timezone_and_updated_at_unchanged(invalid_tz):
    past = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    pref = PersonPreference(
        person_id="U12345",
        preferred_timezone="Asia/Kolkata",
        updated_at=past,
    )

    with pytest.raises(ValueError):
        pref.update_preferred_timezone(invalid_tz)  # type: ignore[arg-type]

    assert pref.preferred_timezone == "Asia/Kolkata"
    assert pref.updated_at == past


# =====================================================================
# 5. Atomicity
# =====================================================================


def test_failed_policy_update_does_not_mutate_state():
    initial_policy = SignoffReminderPolicy.CONTINUE
    initial_tz = "Asia/Kolkata"
    past = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    pref = PersonPreference(
        person_id="U12345",
        reminders_after_signoff=initial_policy,
        preferred_timezone=initial_tz,
        updated_at=past,
    )

    with pytest.raises(ValueError):
        pref.update_reminders_after_signoff("unsupported_policy")

    assert pref.reminders_after_signoff == initial_policy
    assert pref.preferred_timezone == initial_tz
    assert pref.updated_at == past


def test_failed_timezone_update_does_not_mutate_state():
    initial_policy = SignoffReminderPolicy.PAUSE_UNTIL_NEXT_WORKDAY
    initial_tz = "Asia/Kolkata"
    past = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    pref = PersonPreference(
        person_id="U12345",
        reminders_after_signoff=initial_policy,
        preferred_timezone=initial_tz,
        updated_at=past,
    )

    with pytest.raises(ValueError):
        pref.update_preferred_timezone("Invalid/Zone")

    assert pref.reminders_after_signoff == initial_policy
    assert pref.preferred_timezone == initial_tz
    assert pref.updated_at == past


def test_constructor_failure_on_invalid_policy_leaves_no_aggregate():
    with pytest.raises(ValueError):
        PersonPreference(
            person_id="U12345",
            reminders_after_signoff="invalid_policy",
        )


def test_constructor_failure_on_invalid_timezone_leaves_no_aggregate():
    with pytest.raises(ValueError):
        PersonPreference(
            person_id="U12345",
            preferred_timezone="Invalid/Zone",
        )
