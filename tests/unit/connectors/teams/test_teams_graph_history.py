"""
Unit tests for Microsoft Graph Teams history, replies, chat, throttling, and permissions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
import requests

from connectors.microsoft_teams.services.teams_graph_client import (
    TeamsGraphClient,
    TeamsGraphPermissionError,
    TeamsGraphRateLimitError,
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


def test_get_channel_messages_and_normalization():
    client = TeamsGraphClient(token_provider="fake-token")

    raw_teams_payload = {
        "value": [
            {
                "id": "msg_001",
                "createdDateTime": "2026-11-05T10:00:00Z",
                "from": {
                    "user": {
                        "id": "user_teams_1",
                        "displayName": "Akshat Tripathi",
                    }
                },
                "body": {
                    "content": "Teams channel message regarding automation.",
                },
                "attachments": [],
            }
        ]
    }

    with patch("requests.get", return_value=_make_response(200, raw_teams_payload)):
        page = client.get_channel_messages(team_id="team_1", channel_id="ch_1")
        assert len(page["value"]) == 1

        norm = client.normalize_teams_message(page["value"][0], team_id="team_1", channel_id="ch_1")
        assert norm["id"] == "msg_001"
        assert norm["sender_name"] == "Akshat Tripathi"
        assert norm["text"] == "Teams channel message regarding automation."
        assert norm["channel_id"] == "ch_1"
        assert norm["team_id"] == "team_1"
        assert norm["source"] == "microsoft_teams"


def test_get_message_replies():
    client = TeamsGraphClient(token_provider="fake-token")
    raw_replies = {
        "value": [
            {
                "id": "reply_001",
                "createdDateTime": "2026-11-05T10:05:00Z",
                "replyToId": "msg_001",
                "from": {"user": {"id": "user_2", "displayName": "Vijay Sharma"}},
                "body": {"content": "Replying to msg_001"},
            }
        ]
    }
    with patch("requests.get", return_value=_make_response(200, raw_replies)):
        rep = client.get_message_replies(team_id="team_1", channel_id="ch_1", message_id="msg_001")
        assert len(rep["value"]) == 1
        assert rep["value"][0]["id"] == "reply_001"


def test_chat_messages_and_send_chat_message():
    client = TeamsGraphClient(token_provider="fake-token")

    with patch("requests.get", return_value=_make_response(200, {"value": [{"id": "c_1", "body": {"content": "chat"}}]})), \
         patch("requests.post", return_value=_make_response(201, {"id": "c_new", "body": {"content": "summary sent"}})) as mock_post:
        msgs = client.get_chat_messages(chat_id="chat_123")
        assert len(msgs["value"]) == 1

        sent = client.send_chat_message(chat_id="chat_123", text="summary sent")
        assert sent["id"] == "c_new"
        mock_post.assert_called_once()


def test_teams_throttling_retry_after():
    client = TeamsGraphClient(token_provider="fake-token")

    resp_429 = _make_response(429, headers={"Retry-After": "0.01"})
    resp_200 = _make_response(200, {"value": []})

    with patch("requests.get", side_effect=[resp_429, resp_200]), \
         patch("time.sleep") as mock_sleep:
        res = client.get_channel_messages("team_1", "ch_1")
        assert res["value"] == []
        mock_sleep.assert_called_once_with(0.01)

    # 429 exhaustion raises TeamsGraphRateLimitError
    with patch("requests.get", return_value=_make_response(429, headers={"Retry-After": "0.01"})), \
         patch("time.sleep"):
        with pytest.raises(TeamsGraphRateLimitError):
            client.get_channel_messages("team_1", "ch_1")


def test_teams_permission_error_403():
    client = TeamsGraphClient(token_provider="fake-token")
    err_payload = {
        "error": {
            "code": "Authorization_RequestDenied",
            "message": "Insufficient privileges to complete the operation.",
        }
    }
    with patch("requests.get", return_value=_make_response(403, err_payload)):
        with pytest.raises(TeamsGraphPermissionError) as exc_info:
            client.get_channel_messages("team_1", "ch_1")
        assert "ChannelMessage.Read.All" in str(exc_info.value)
        assert "403 Forbidden" in str(exc_info.value)
