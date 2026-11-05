from unittest.mock import Mock, call, patch

import pytest

from engines.slack.services.slack_identity_service import (
    SlackIdentityService,
    SlackRateLimitError,
)


class _FakeResponse:
    def __init__(self, *, ok=True, payload=None, status_code=200, headers=None):
        self.ok = ok
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {"ok": ok, "members": []}
        self.raise_for_status = Mock()

    def json(self):
        return self._payload


def test_get_conversation_members_paginates_and_deduplicates():
    service = SlackIdentityService()
    first = _FakeResponse(
        payload={
            "ok": True,
            "members": ["U1", "U2", "U2"],
            "response_metadata": {"next_cursor": "cursor-1"},
        }
    )
    second = _FakeResponse(
        payload={
            "ok": True,
            "members": ["U3", "U1"],
            "response_metadata": {},
        }
    )

    with patch("engines.slack.services.slack_identity_service.requests.get", side_effect=[first, second]):
        members = service.get_conversation_members("C123")

    assert members == ["U1", "U2", "U3"]


def test_get_conversation_members_rejects_invalid_channel_id():
    service = SlackIdentityService()

    with pytest.raises(ValueError):
        service.get_conversation_members("   ")


def test_get_conversation_members_handles_ok_false():
    service = SlackIdentityService()
    response = _FakeResponse(ok=False, payload={"ok": False, "error": "channel_not_found"})

    with patch("engines.slack.services.slack_identity_service.requests.get", return_value=response):
        with pytest.raises(RuntimeError, match="channel_not_found"):
            service.get_conversation_members("C404")


def test_get_conversation_members_uses_cache():
    service = SlackIdentityService()
    first = _FakeResponse(
        payload={
            "ok": True,
            "members": ["U1", "U2"],
            "response_metadata": {},
        }
    )

    with patch("engines.slack.services.slack_identity_service.requests.get", return_value=first) as mock_get:
        first_result = service.get_conversation_members("C123")
        second_result = service.get_conversation_members("C123")

    assert first_result == ["U1", "U2"]
    assert second_result == ["U1", "U2"]
    assert mock_get.call_count == 1


# =============================================================================
# RATE LIMITING & BOUNDED RETRY TESTS (HTTP 429)
# =============================================================================

def test_get_conversation_members_successful_retry_after_429():
    """Verify that a single 429 respects Retry-After and returns full members on retry."""
    service = SlackIdentityService()
    resp_429 = _FakeResponse(
        status_code=429,
        headers={"Retry-After": "2.5"},
    )
    resp_200 = _FakeResponse(
        status_code=200,
        payload={
            "ok": True,
            "members": ["U_ALICE", "U_BOB"],
            "response_metadata": {},
        },
    )

    with patch("engines.slack.services.slack_identity_service.requests.get", side_effect=[resp_429, resp_200]) as mock_get, \
         patch("engines.slack.services.slack_identity_service.time.sleep") as mock_sleep:
        members = service.get_conversation_members("C123")

    assert members == ["U_ALICE", "U_BOB"]
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(2.5)


def test_get_conversation_members_repeated_429_then_success():
    """Verify multiple 429s up to 2 retries respect each Retry-After and succeed on 3rd attempt."""
    service = SlackIdentityService()
    resp_429_first = _FakeResponse(status_code=429, headers={"Retry-After": "1.5"})
    resp_429_second = _FakeResponse(status_code=429, headers={"Retry-After": "3.0"})
    resp_200 = _FakeResponse(
        status_code=200,
        payload={
            "ok": True,
            "members": ["U_CHARLIE"],
            "response_metadata": {},
        },
    )

    with patch("engines.slack.services.slack_identity_service.requests.get", side_effect=[resp_429_first, resp_429_second, resp_200]) as mock_get, \
         patch("engines.slack.services.slack_identity_service.time.sleep") as mock_sleep:
        members = service.get_conversation_members("C_REPEATED")

    assert members == ["U_CHARLIE"]
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list == [call(1.5), call(3.0)]


def test_get_conversation_members_exhausted_retries_raises_controlled_exception():
    """Verify that exceeding 3 retries (4 attempts total) raises SlackRateLimitError / RuntimeError."""
    service = SlackIdentityService()
    responses = [
        _FakeResponse(status_code=429, headers={"Retry-After": "1.0"})
        for _ in range(5)
    ]

    with patch("engines.slack.services.slack_identity_service.requests.get", side_effect=responses) as mock_get, \
         patch("engines.slack.services.slack_identity_service.time.sleep") as mock_sleep:
        with pytest.raises(SlackRateLimitError) as exc_info:
            service.get_conversation_members("C_EXHAUST")

    # Initial request + 3 retries = 4 requests total
    assert mock_get.call_count == 4
    # Sleep called 3 times for the 3 retries
    assert mock_sleep.call_count == 3
    assert "rate limit exceeded after 3 retries" in str(exc_info.value)
    # Cache must NOT be populated on failure
    assert "C_EXHAUST" not in service._member_cache


def test_get_conversation_members_does_not_return_incomplete_membership_on_later_page_failure():
    """
    If page 1 succeeds but page 2 rate limits and exhausts retries,
    do NOT return partial membership from page 1 and do NOT cache it.
    """
    service = SlackIdentityService()
    page1 = _FakeResponse(
        status_code=200,
        payload={
            "ok": True,
            "members": ["U_PAGE1_MEMBER"],
            "response_metadata": {"next_cursor": "cursor-2"},
        },
    )
    # Page 2 fails with 429s
    page2_429s = [
        _FakeResponse(status_code=429, headers={"Retry-After": "0.5"})
        for _ in range(4)
    ]

    with patch("engines.slack.services.slack_identity_service.requests.get", side_effect=[page1, *page2_429s]), \
         patch("engines.slack.services.slack_identity_service.time.sleep"):
        with pytest.raises(SlackRateLimitError):
            service.get_conversation_members("C_MULTI_PAGE_FAIL")

    # Partial membership must NOT be cached
    assert "C_MULTI_PAGE_FAIL" not in service._member_cache


def test_get_conversation_members_cursor_cycle_detected():
    """Verify that a pagination cycle raises a controlled exception rather than looping forever."""
    service = SlackIdentityService()
    page1 = _FakeResponse(
        status_code=200,
        payload={
            "ok": True,
            "members": ["U1"],
            "response_metadata": {"next_cursor": "loop-cursor"},
        },
    )
    page2 = _FakeResponse(
        status_code=200,
        payload={
            "ok": True,
            "members": ["U2"],
            "response_metadata": {"next_cursor": "loop-cursor"},
        },
    )

    with patch("engines.slack.services.slack_identity_service.requests.get", side_effect=[page1, page2]):
        with pytest.raises(RuntimeError, match="cursor cycle detected"):
            service.get_conversation_members("C_CYCLE")


def test_get_conversation_members_default_retry_after_when_header_invalid_or_missing():
    """When Retry-After header is missing or non-numeric, default to 1.0 second sleep."""
    service = SlackIdentityService()
    resp_no_header = _FakeResponse(status_code=429, headers={})
    resp_bad_header = _FakeResponse(status_code=429, headers={"Retry-After": "invalid_seconds"})
    resp_200 = _FakeResponse(
        status_code=200,
        payload={"ok": True, "members": ["U_OK"], "response_metadata": {}},
    )

    with patch("engines.slack.services.slack_identity_service.requests.get", side_effect=[resp_no_header, resp_bad_header, resp_200]) as mock_get, \
         patch("engines.slack.services.slack_identity_service.time.sleep") as mock_sleep:
        members = service.get_conversation_members("C_DEFAULTS")

    assert members == ["U_OK"]
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list == [call(1.0), call(1.0)]
