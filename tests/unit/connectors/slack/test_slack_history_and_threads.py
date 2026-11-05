"""
Unit tests for SlackClient conversation history, thread replies, pagination, and rate limit handling.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
import requests

from engines.slack.services.slack_client import (
    SlackClient,
    SlackRateLimitError,
)


def _make_response(status_code: int = 200, json_data: dict | None = None, headers: dict | None = None) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = (
        requests.compat.json.dumps(json_data or {}).encode("utf-8")
        if json_data is not None
        else b"{}"
    )
    if headers:
        resp.headers.update(headers)
    return resp


def test_get_conversation_history_basic():
    client = SlackClient(token="xoxb-test")
    fake_payload = {
        "ok": True,
        "messages": [
            {"ts": "1600000001.000", "text": "Hello channel", "user": "U123"},
            {"ts": "1600000002.000", "text": "Next update", "user": "U456"},
        ],
        "has_more": True,
        "response_metadata": {"next_cursor": "cur_123"},
    }

    with patch("requests.get", return_value=_make_response(200, fake_payload)) as mock_get:
        res = client.get_conversation_history(
            channel="C0BG7NWMD6D",
            oldest="1600000000",
            latest="1600000005",
            limit=50,
        )
        assert res["has_more"] is True
        assert res["next_cursor"] == "cur_123"
        assert len(res["messages"]) == 2

        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["channel"] == "C0BG7NWMD6D"
        assert kwargs["params"]["oldest"] == "1600000000"
        assert kwargs["params"]["latest"] == "1600000005"


def test_get_conversation_replies():
    client = SlackClient(token="xoxb-test")
    fake_replies = {
        "ok": True,
        "messages": [
            {"ts": "1600000001.000", "text": "Root message", "user": "U123", "thread_ts": "1600000001.000"},
            {"ts": "1600000002.000", "text": "Reply 1", "user": "U456", "thread_ts": "1600000001.000"},
        ],
        "has_more": False,
    }

    with patch("requests.get", return_value=_make_response(200, fake_replies)) as mock_get:
        res = client.get_conversation_replies(
            channel="C0BG7NWMD6D",
            ts="1600000001.000",
        )
        assert res["has_more"] is False
        assert len(res["messages"]) == 2
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["ts"] == "1600000001.000"


def test_get_all_channel_messages_with_replies_and_filtering():
    client = SlackClient(token="xoxb-test")

    history_page = {
        "ok": True,
        "messages": [
            {
                "ts": "1600000001.000",
                "text": "Parent message with discussion",
                "user": "U123",
                "thread_ts": "1600000001.000",
                "reply_count": 1,
            },
            {
                "ts": "1600000002.000",
                "subtype": "message_deleted",
                "text": "I was deleted",
            },
            {
                "ts": "1600000003.000",
                "subtype": "message_changed",
                "message": {
                    "ts": "1600000003.000",
                    "text": "Edited text content",
                    "user": "U789",
                },
            },
        ],
        "has_more": False,
    }

    replies_page = {
        "ok": True,
        "messages": [
            {"ts": "1600000001.000", "text": "Parent message with discussion", "user": "U123"},
            {"ts": "1600000001.500", "text": "Thread reply here", "user": "U456", "thread_ts": "1600000001.000"},
        ],
        "has_more": False,
    }

    def _mock_get(url, **kwargs):
        if "conversations.history" in url:
            return _make_response(200, history_page)
        elif "conversations.replies" in url:
            return _make_response(200, replies_page)
        return _make_response(404, {"ok": False})

    with patch("requests.get", side_effect=_mock_get):
        all_msgs = client.get_all_channel_messages(channel="C0BG7NWMD6D", max_messages=100)
        # Should include: Parent (1600000001.000), Reply (1600000001.500), Edited (1600000003.000)
        # Should exclude: Deleted message
        texts = [m["text"] for m in all_msgs]
        assert "Parent message with discussion" in texts
        assert "Thread reply here" in texts
        assert "Edited text content" in texts
        assert "I was deleted" not in texts


def test_send_dm_workflow():
    client = SlackClient(token="xoxb-test")

    with patch.object(client, "open_dm", return_value="D12345678") as mock_open, \
         patch.object(client, "post_message") as mock_post:
        dm_ch = client.send_dm(user_id="U0BU41F6CTD", text="Confidential summary")
        assert dm_ch == "D12345678"
        mock_open.assert_called_once_with("U0BU41F6CTD")
        mock_post.assert_called_once_with(channel="D12345678", text="Confidential summary")


def test_rate_limit_retry_after_and_exhaustion():
    client = SlackClient(token="xoxb-test")

    # 429 then success
    resp_429 = _make_response(429, headers={"Retry-After": "0.01"})
    resp_200 = _make_response(200, {"ok": True, "messages": []})

    with patch("requests.get", side_effect=[resp_429, resp_200]), \
         patch("time.sleep") as mock_sleep:
        res = client.get_conversation_history("C123")
        assert res["messages"] == []
        mock_sleep.assert_called_once_with(0.01)

    # Exhaustion raises SlackRateLimitError
    with patch("requests.get", return_value=_make_response(429, headers={"Retry-After": "0.01"})), \
         patch("time.sleep"):
        with pytest.raises(SlackRateLimitError):
            client.get_conversation_history("C123")
