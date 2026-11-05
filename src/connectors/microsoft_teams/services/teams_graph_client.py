"""
Microsoft Graph Teams Conversation and Chat Client.

Retrieves authorized organizational conversations from Microsoft Teams via Microsoft Graph:
- Channel messages and threaded replies.
- 1-on-1 and group chat history.
- Online meeting conversations/transcripts where available.
- Pagination, rate-limit throttling (HTTP 429), and permission verification.

Required Microsoft Graph Permissions:
- Application Permissions:
  * ChannelMessage.Read.All: Read all channel messages in teams.
  * Chat.Read.All: Read all 1-on-1 and group chats.
  * Chat.ReadWrite: Send private responses and notifications to chats.
  * Team.ReadBasic.All: Read basic team properties.
  * OnlineMeetings.Read.All: Read online meeting transcripts and metadata.
- Delegated Permissions (when user delegated context is used):
  * ChannelMessage.Read.All
  * Chat.Read
  * Chat.ReadWrite
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)


class TeamsGraphRateLimitError(RuntimeError):
    """Raised when Microsoft Graph throttling (HTTP 429) retries are exhausted."""


class TeamsGraphPermissionError(PermissionError):
    """Raised when Microsoft Graph returns HTTP 403 Forbidden due to missing scopes/permissions."""


class TeamsGraphClient:
    """
    Client for Microsoft Graph Teams and Chat APIs.
    """

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    MAX_RETRIES = 3

    def __init__(
        self,
        token_provider: Callable[[], str] | str | None = None,
        base_url: str = GRAPH_BASE_URL,
    ) -> None:
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")

    def _get_token(self) -> str:
        if callable(self._token_provider):
            return self._token_provider()
        if isinstance(self._token_provider, str) and self._token_provider:
            return self._token_provider
        # Lazy fallback to MicrosoftGraphTokenProvider
        from infrastructure.meetings.microsoft_graph_token_provider import MicrosoftGraphTokenProvider
        provider = MicrosoftGraphTokenProvider()
        return provider()

    def _extract_retry_after(self, response: requests.Response, default: float = 2.0) -> float:
        header_val = response.headers.get("Retry-After")
        if header_val is not None:
            try:
                val = float(header_val)
                if val >= 0:
                    return val
            except (ValueError, TypeError):
                pass
        return default

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: int = 20,
    ) -> dict[str, Any]:
        """
        Execute an HTTP request against Microsoft Graph with bounded retries for 429 throttling
        and clear permission error reporting for 403.
        """
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        retries = 0
        target_url = url if url.startswith("http") else f"{self._base_url}/{url.lstrip('/')}"

        while True:
            try:
                if method.upper() == "GET":
                    response = requests.get(target_url, headers=headers, params=params, timeout=timeout)
                elif method.upper() == "POST":
                    response = requests.post(target_url, headers=headers, json=json_data, params=params, timeout=timeout)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                if response.status_code == 429:
                    retries += 1
                    if retries > self.MAX_RETRIES:
                        raise TeamsGraphRateLimitError(
                            f"Microsoft Graph rate limit (429) exceeded after {retries - 1} retries for {target_url}."
                        )
                    wait_time = self._extract_retry_after(response)
                    logger.warning(
                        "Microsoft Graph 429 throttling for %s. Sleeping %.2fs (attempt %d/%d)",
                        target_url,
                        wait_time,
                        retries,
                        self.MAX_RETRIES,
                    )
                    time.sleep(wait_time)
                    continue

                if response.status_code == 403:
                    error_detail = response.text
                    try:
                        err_json = response.json()
                        error_detail = err_json.get("error", {}).get("message", error_detail)
                    except Exception:
                        pass
                    raise TeamsGraphPermissionError(
                        f"Microsoft Graph 403 Forbidden for {target_url}. "
                        f"Verify required Azure AD application permissions (ChannelMessage.Read.All, Chat.Read.All). "
                        f"Details: {error_detail}"
                    )

                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    retries += 1
                    if retries > self.MAX_RETRIES:
                        raise TeamsGraphRateLimitError(
                            f"Microsoft Graph rate limit (429) exceeded after {retries - 1} retries."
                        ) from exc
                    wait_time = self._extract_retry_after(exc.response)
                    time.sleep(wait_time)
                    continue
                raise

    def get_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        top: int = 50,
        next_link: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve messages in a team channel.
        Requires: ChannelMessage.Read.All
        """
        if next_link:
            return self._request("GET", next_link)

        url = f"teams/{team_id}/channels/{channel_id}/messages"
        params = {"$top": min(max(1, top), 50)}
        return self._request("GET", url, params=params)

    def get_message_replies(
        self,
        team_id: str,
        channel_id: str,
        message_id: str,
        top: int = 50,
        next_link: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve replies to a root channel message.
        Requires: ChannelMessage.Read.All
        """
        if next_link:
            return self._request("GET", next_link)

        url = f"teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
        params = {"$top": min(max(1, top), 50)}
        return self._request("GET", url, params=params)

    def get_chat_messages(
        self,
        chat_id: str,
        top: int = 50,
        next_link: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve messages from a 1-on-1 or group chat.
        Requires: Chat.Read.All
        """
        if next_link:
            return self._request("GET", next_link)

        url = f"chats/{chat_id}/messages"
        params = {"$top": min(max(1, top), 50)}
        return self._request("GET", url, params=params)

    def send_chat_message(
        self,
        chat_id: str,
        text: str,
    ) -> dict[str, Any]:
        """
        Send a message to a chat thread (for private summary delivery).
        Requires: Chat.ReadWrite
        """
        url = f"chats/{chat_id}/messages"
        body = {
            "body": {
                "contentType": "text",
                "content": text,
            }
        }
        return self._request("POST", url, json_data=body)

    def get_all_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        max_messages: int = 150,
        include_replies: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Retrieve paginated messages for a team channel up to max_messages,
        optionally expanding replies.
        """
        messages: list[dict[str, Any]] = []
        next_link: str | None = None

        while len(messages) < max_messages:
            page = self.get_channel_messages(
                team_id=team_id,
                channel_id=channel_id,
                top=min(50, max_messages - len(messages)),
                next_link=next_link,
            )
            raw_items = page.get("value", [])
            for item in raw_items:
                normalized = self.normalize_teams_message(item, team_id=team_id, channel_id=channel_id)
                messages.append(normalized)

            next_link = page.get("@odata.nextLink")
            if not next_link or not raw_items:
                break

        if include_replies:
            expanded: list[dict[str, Any]] = []
            for msg in messages:
                msg_id = msg.get("id")
                # If message has replies
                if msg_id and not msg.get("replyToId"):
                    try:
                        reply_page = self.get_message_replies(
                            team_id=team_id,
                            channel_id=channel_id,
                            message_id=msg_id,
                            top=20,
                        )
                        for r_item in reply_page.get("value", []):
                            norm_r = self.normalize_teams_message(
                                r_item,
                                team_id=team_id,
                                channel_id=channel_id,
                                parent_id=msg_id,
                            )
                            expanded.append(norm_r)
                    except Exception as exc:
                        logger.warning("Could not fetch replies for Teams message %s: %s", msg_id, exc)

            messages.extend(expanded)

        # Sort chronologically by createdDateTime
        messages.sort(key=lambda m: m.get("createdDateTime", ""))
        return messages

    @staticmethod
    def normalize_teams_message(
        raw_msg: dict[str, Any],
        team_id: str = "",
        channel_id: str = "",
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Normalize a raw Microsoft Graph message into a standardized format.
        """
        sender_info = raw_msg.get("from") or {}
        user_info = sender_info.get("user") or {}
        sender_id = user_info.get("id") or ""
        sender_name = user_info.get("displayName") or ""

        body_info = raw_msg.get("body") or {}
        content = body_info.get("content") or ""

        return {
            "id": raw_msg.get("id", ""),
            "replyToId": parent_id or raw_msg.get("replyToId"),
            "sender_id": sender_id,
            "sender_name": sender_name,
            "text": content,
            "createdDateTime": raw_msg.get("createdDateTime", ""),
            "lastModifiedDateTime": raw_msg.get("lastModifiedDateTime", ""),
            "channel_id": channel_id,
            "team_id": team_id,
            "attachments": raw_msg.get("attachments", []),
            "source": "microsoft_teams",
        }
