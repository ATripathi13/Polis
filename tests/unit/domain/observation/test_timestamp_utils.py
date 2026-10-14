from datetime import datetime, timezone
from types import SimpleNamespace

from domain.observation.rules.timestamp_utils import resolve_occurred_at
from engines.communication.domain.value_objects import Content


def make_communication(metadata=None, created_at=None):
    return SimpleNamespace(
        content=Content(body="Test communication", metadata=metadata or {}),
        created_at=created_at,
    )


def test_resolves_valid_source_timestamp_as_utc():
    communication = make_communication(
        metadata={"source_timestamp": "1712345678.123456"}
    )

    result = resolve_occurred_at(communication)

    assert result == datetime.fromtimestamp(
        1712345678.123456,
        tz=timezone.utc,
    )
    assert result.tzinfo == timezone.utc


def test_falls_back_to_created_at_when_source_timestamp_is_missing():
    created_at = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    communication = make_communication(created_at=created_at)

    assert resolve_occurred_at(communication) == created_at


def test_falls_back_to_created_at_when_source_timestamp_is_invalid():
    created_at = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    communication = make_communication(
        metadata={"source_timestamp": "not-a-timestamp"},
        created_at=created_at,
    )

    assert resolve_occurred_at(communication) == created_at


def test_returns_none_when_source_timestamp_and_created_at_are_missing():
    communication = make_communication()

    assert resolve_occurred_at(communication) is None
