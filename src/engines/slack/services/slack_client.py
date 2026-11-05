"""
Slack Web API client.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class SlackRateLimitError(RuntimeError):
    """Raised when Slack API rate limit retries are exhausted."""


class SlackClient:
    """
    Client for the Slack Web API with support for posting messages,
    opening DMs, file operations, channel history, and thread replies.
    """

    MAX_RETRIES = 3

    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else os.environ.get("SLACK_BOT_TOKEN", "")
        self._url = "https://slack.com/api/chat.postMessage"

    def _extract_retry_after(self, response: Any, default: float = 1.0) -> float:
        """Extract Retry-After header safely, defaulting to `default`."""
        if hasattr(response, "headers") and response.headers:
            header_val = response.headers.get("Retry-After")
            if header_val is not None:
                try:
                    delay = float(header_val)
                    if delay >= 0:
                        return delay
                except (ValueError, TypeError):
                    pass
        return default

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request_json(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: int = 15,
        max_retries: int = MAX_RETRIES,
    ) -> dict[str, Any]:
        """
        Execute an HTTP request against Slack API with bounded retry for HTTP 429 rate limits.
        """
        headers = self._get_headers()
        retries = 0

        while True:
            try:
                if method.upper() == "GET":
                    response = requests.get(url, headers=headers, params=params, timeout=timeout)
                else:
                    response = requests.post(url, headers=headers, json=json_data, params=params, timeout=timeout)

                if response.status_code == 429:
                    retries += 1
                    if retries > max_retries:
                        raise SlackRateLimitError(
                            f"Slack API rate limit exceeded after {retries - 1} retries for {url}."
                        )
                    wait_time = self._extract_retry_after(response)
                    logger.warning(
                        "Slack API 429 rate limited for %s. Sleeping %.2fs (attempt %d/%d)",
                        url,
                        wait_time,
                        retries,
                        max_retries,
                    )
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()

                if not data.get("ok") and data.get("error") == "ratelimited":
                    retries += 1
                    if retries > max_retries:
                        raise SlackRateLimitError(
                            f"Slack API rate limit payload exceeded after {retries - 1} retries for {url}."
                        )
                    wait_time = self._extract_retry_after(response)
                    logger.warning(
                        "Slack API returned 'ratelimited' error for %s. Sleeping %.2fs (attempt %d/%d)",
                        url,
                        wait_time,
                        retries,
                        max_retries,
                    )
                    time.sleep(wait_time)
                    continue

                return data

            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    retries += 1
                    if retries > max_retries:
                        raise SlackRateLimitError(
                            f"Slack API rate limit exceeded after {retries - 1} retries for {url}."
                        ) from exc
                    wait_time = self._extract_retry_after(exc.response)
                    logger.warning(
                        "Slack API HTTPError 429 for %s. Sleeping %.2fs (attempt %d/%d)",
                        url,
                        wait_time,
                        retries,
                        max_retries,
                    )
                    time.sleep(wait_time)
                    continue
                raise

    def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> None:
        """
        Send a message to Slack.
        """
        payload = {
            "channel": channel,
            "text": text,
        }

        if thread_ts:
            payload["thread_ts"] = thread_ts

        headers = {
            "Authorization": (
                f"Bearer {self._token}"
            ),
            "Content-Type": "application/json",
        }

        response = requests.post(
            self._url,
            json=payload,
            headers=headers,
            timeout=10,
        )

        logger.debug(
            "Slack API postMessage responded with status %s",
            response.status_code,
            extra={"operation": "slack_post_message", "status_code": response.status_code},
        )

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get(
                    "error",
                    "Unknown Slack error",
                )
            )

    def open_dm(
        self,
        user_id: str,
    ) -> str:
        """
        Open or retrieve a direct-message conversation
        with a Slack user.
        """
        headers = {
            "Authorization": (
                f"Bearer {self._token}"
            ),
            "Content-Type": "application/json",
        }

        response = requests.post(
            "https://slack.com/api/conversations.open",
            json={
                "users": user_id,
            },
            headers=headers,
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get(
                    "error",
                    "Failed to open Slack DM.",
                )
            )

        channel = data.get("channel", {})

        channel_id = channel.get("id")

        if not channel_id:
            raise RuntimeError(
                "Slack did not return a DM channel ID."
            )

        return channel_id

    def get_file_info(
        self,
        file_id: str,
    ) -> dict:
        """
        Retrieve metadata for a Slack file.
        """
        headers = {
            "Authorization": (
                f"Bearer {self._token}"
            ),
        }

        response = requests.get(
            "https://slack.com/api/files.info",
            headers=headers,
            params={
                "file": file_id,
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get(
                    "error",
                    "Failed to retrieve Slack file.",
                )
            )

        return data["file"]

    def download_file(
        self,
        file_url: str,
    ) -> bytes:
        """
        Download a Slack-hosted file using the bot token.
        """
        headers = {
            "Authorization": (
                f"Bearer {self._token}"
            ),
        }

        response = requests.get(
            file_url,
            headers=headers,
            timeout=60,
        )

        response.raise_for_status()

        return response.content

    def send_dm(
        self,
        user_id: str,
        text: str,
    ) -> str:
        """
        Open a direct message conversation with user_id and post a message privately.
        Returns the DM channel ID.
        """
        dm_channel = self.open_dm(user_id)
        self.post_message(channel=dm_channel, text=text)
        return dm_channel

    def get_conversation_history(
        self,
        channel: str,
        oldest: str | None = None,
        latest: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        inclusive: bool = True,
    ) -> dict[str, Any]:
        """
        Retrieve messages from a Slack channel (public, private, DM, or MPIM).
        Respects pagination, time ranges, and rate limits.
        """
        if not channel or not channel.strip():
            raise ValueError("Channel ID cannot be empty.")

        params: dict[str, Any] = {
            "channel": channel.strip(),
            "limit": min(max(1, limit), 200),
            "inclusive": "true" if inclusive else "false",
        }
        if oldest:
            params["oldest"] = str(oldest).strip()
        if latest:
            params["latest"] = str(latest).strip()
        if cursor:
            params["cursor"] = str(cursor).strip()

        data = self._request_json(
            "GET",
            "https://slack.com/api/conversations.history",
            params=params,
        )

        if not data.get("ok"):
            error_code = data.get("error", "unknown_error")
            raise RuntimeError(f"Failed to retrieve conversation history for {channel}: {error_code}")

        messages = data.get("messages", [])
        has_more = bool(data.get("has_more", False))
        next_cursor = data.get("response_metadata", {}).get("next_cursor") or None

        return {
            "messages": messages,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    def get_conversation_replies(
        self,
        channel: str,
        ts: str,
        oldest: str | None = None,
        latest: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve reply thread messages for a specific message thread.
        """
        if not channel or not channel.strip():
            raise ValueError("Channel ID cannot be empty.")
        if not ts or not ts.strip():
            raise ValueError("Thread timestamp 'ts' cannot be empty.")

        params: dict[str, Any] = {
            "channel": channel.strip(),
            "ts": str(ts).strip(),
            "limit": min(max(1, limit), 200),
        }
        if oldest:
            params["oldest"] = str(oldest).strip()
        if latest:
            params["latest"] = str(latest).strip()
        if cursor:
            params["cursor"] = str(cursor).strip()

        data = self._request_json(
            "GET",
            "https://slack.com/api/conversations.replies",
            params=params,
        )

        if not data.get("ok"):
            error_code = data.get("error", "unknown_error")
            raise RuntimeError(f"Failed to retrieve conversation replies for {channel} ts {ts}: {error_code}")

        messages = data.get("messages", [])
        has_more = bool(data.get("has_more", False))
        next_cursor = data.get("response_metadata", {}).get("next_cursor") or None

        return {
            "messages": messages,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    def get_all_channel_messages(
        self,
        channel: str,
        oldest: str | None = None,
        latest: str | None = None,
        max_messages: int = 200,
        include_replies: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Retrieve paginated channel history up to max_messages, optionally expanding
        in-place thread replies. Handles edited/deleted messages and cycle detection.
        """
        seen_cursors: set[str] = set()
        collected_messages: list[dict[str, Any]] = []
        cursor: str | None = None

        while len(collected_messages) < max_messages:
            page_limit = min(100, max_messages - len(collected_messages))
            page = self.get_conversation_history(
                channel=channel,
                oldest=oldest,
                latest=latest,
                limit=page_limit,
                cursor=cursor,
            )

            raw_msgs = page.get("messages", [])
            for msg in raw_msgs:
                subtype = msg.get("subtype", "")
                if subtype == "message_deleted":
                    continue
                # Handle edited messages: unpack newest content if present
                if subtype == "message_changed" and "message" in msg:
                    normalized_msg = dict(msg["message"])
                    normalized_msg["channel"] = channel
                    collected_messages.append(normalized_msg)
                else:
                    msg_copy = dict(msg)
                    msg_copy["channel"] = channel
                    collected_messages.append(msg_copy)

            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break

            if cursor in seen_cursors:
                logger.warning("Pagination cycle detected for channel %s at cursor %s", channel, cursor)
                break
            seen_cursors.add(cursor)

        if include_replies:
            # Fetch replies for threaded messages that had replies
            expanded_threads: list[dict[str, Any]] = []
            for msg in collected_messages:
                thread_ts = msg.get("thread_ts")
                msg_ts = msg.get("ts")
                reply_count = msg.get("reply_count", 0)
                # If this is a thread parent with replies, fetch child replies
                if thread_ts == msg_ts and reply_count > 0:
                    try:
                        rep_page = self.get_conversation_replies(
                            channel=channel,
                            ts=msg_ts,
                            limit=min(reply_count + 1, 100),
                        )
                        # First message is the parent, following are replies
                        for reply in rep_page.get("messages", [])[1:]:
                            if reply.get("subtype") == "message_deleted":
                                continue
                            rep_copy = dict(reply)
                            rep_copy["channel"] = channel
                            expanded_threads.append(rep_copy)
                    except Exception as exc:
                        logger.warning("Failed to fetch replies for thread %s in channel %s: %s", msg_ts, channel, exc)

            collected_messages.extend(expanded_threads)

        # Sort chronologically by float(ts)
        def _get_ts(m: dict[str, Any]) -> float:
            try:
                return float(m.get("ts", 0))
            except (ValueError, TypeError):
                return 0.0

        collected_messages.sort(key=_get_ts)
        return collected_messages
