"""
Slack user identity service.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()


class SlackRateLimitError(RuntimeError):
    """Raised when Slack API rate limit retries are exhausted."""
    pass


class SlackIdentityService:
    """
    Resolves Slack user identities dynamically from the workspace.
    """

    MEMBERSHIP_CACHE_TTL_SECONDS = 300
    MAX_RETRIES_PER_PAGE = 3

    def __init__(self) -> None:
        self._token = os.environ.get("SLACK_BOT_TOKEN", "")

        self._headers = {
            "Authorization": f"Bearer {self._token}",
        }

        self._users_info_url = "https://slack.com/api/users.info"
        self._users_list_url = "https://slack.com/api/users.list"
        self._conversations_members_url = "https://slack.com/api/conversations.members"

        self._directory: list[dict] | None = None
        self._member_cache: dict[str, tuple[float, list[str]]] = {}
        self._cache_lock = threading.RLock()

    @staticmethod
    def _extract_retry_after(response: Any, default: float = 1.0) -> float:
        headers = getattr(response, "headers", None) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is not None:
            try:
                val = float(raw)
                if val >= 0:
                    return val
            except (TypeError, ValueError):
                pass
        return default

    def _request_json(
        self,
        url: str,
        *,
        params: dict | None = None,
        timeout: int = 10,
        max_retries: int | None = None,
    ) -> dict:
        limit = max_retries if max_retries is not None else self.MAX_RETRIES_PER_PAGE
        retries = 0

        while True:
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=self._headers,
                    timeout=timeout,
                )
            except requests.exceptions.HTTPError as exc:
                if getattr(exc.response, "status_code", None) == 429:
                    response = exc.response
                else:
                    raise

            if response.status_code == 429:
                if retries >= limit:
                    raise SlackRateLimitError(
                        f"Slack API rate limit exceeded after {retries} retries for {url}."
                    )
                retries += 1
                retry_after = self._extract_retry_after(response, default=1.0)
                time.sleep(retry_after)
                continue

            response.raise_for_status()

            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("Slack API returned a non-dictionary payload.")

            if not data.get("ok"):
                error_code = data.get("error", "Slack API request failed.")
                if error_code == "ratelimited":
                    if retries >= limit:
                        raise SlackRateLimitError(
                            f"Slack API rate limit exceeded after {retries} retries for {url}."
                        )
                    retries += 1
                    retry_after = self._extract_retry_after(response, default=1.0)
                    time.sleep(retry_after)
                    continue
                raise RuntimeError(error_code)

            return data

    def get_conversation_members(
        self,
        channel_id: str,
        refresh: bool = False,
        ttl_seconds: float | None = None,
    ) -> list[str]:
        """
        Retrieve the verified member IDs for a Slack conversation.

        This uses the official conversations.members endpoint, paginates through
        every page, and caches the result for a limited TTL.
        """
        clean_channel_id = (channel_id or "").strip()
        if not clean_channel_id:
            raise ValueError("Slack conversation ID is required.")

        ttl = ttl_seconds if ttl_seconds is not None else self.MEMBERSHIP_CACHE_TTL_SECONDS
        now = time.monotonic()

        with self._cache_lock:
            cached = self._member_cache.get(clean_channel_id)
            if cached and not refresh and now < cached[0] + ttl:
                return list(cached[1])

        all_members: set[str] = set()
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            params = {
                "channel": clean_channel_id,
                "limit": "200",
            }
            if cursor:
                params["cursor"] = cursor

            try:
                data = self._request_json(
                    self._conversations_members_url,
                    params=params,
                    timeout=10,
                )
            except requests.exceptions.RequestException as exc:
                raise RuntimeError(
                    f"Failed to retrieve Slack conversation members for {clean_channel_id}."
                ) from exc

            page_members = data.get("members") or []
            for member_id in page_members:
                normalized = str(member_id).strip()
                if not normalized:
                    continue
                if normalized.upper() in {"USLACKBOT"}:
                    continue
                if normalized.startswith("B"):
                    continue
                all_members.add(normalized)

            response_metadata = data.get("response_metadata") or {}
            next_cursor = response_metadata.get("next_cursor") or None
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError(
                    f"Pagination cursor cycle detected for conversation {clean_channel_id}: {next_cursor}"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        normalized_members = sorted(all_members)

        with self._cache_lock:
            self._member_cache[clean_channel_id] = (time.monotonic(), normalized_members)

        return normalized_members

    def get_verified_conversation_members(
        self,
        channel_id: str,
        refresh: bool = False,
        ttl_seconds: float | None = None,
    ) -> list[str]:
        return self.get_conversation_members(channel_id, refresh=refresh, ttl_seconds=ttl_seconds)

    def get_channel_members(
        self,
        channel_id: str,
        refresh: bool = False,
        ttl_seconds: float | None = None,
    ) -> list[str]:
        return self.get_conversation_members(channel_id, refresh=refresh, ttl_seconds=ttl_seconds)

    def get_display_name(
        self,
        user_id: str,
    ) -> str:
        """
        Resolve a Slack user ID into a human-readable name.
        """
        data = self._request_json(
            self._users_info_url,
            params={"user": user_id},
            timeout=10,
        )

        user = data.get("user", {})
        return self._display_name_from_user(user, fallback=user_id)

    def get_workspace_users(
        self,
        refresh: bool = False,
    ) -> list[dict]:
        """
        Retrieve the current Slack workspace users dynamically.

        The result is cached for the lifetime of this service instance.
        """
        if self._directory is not None and not refresh:
            return self._directory

        users: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            params: dict[str, str] = {"limit": "200"}
            if cursor:
                params["cursor"] = cursor

            data = self._request_json(
                self._users_list_url,
                params=params,
                timeout=10,
            )

            users.extend(data.get("members", []))
            response_metadata = data.get("response_metadata") or {}
            next_cursor = response_metadata.get("next_cursor") or None
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError(f"Pagination cursor cycle detected in users.list: {next_cursor}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        self._directory = users
        return users

    def resolve_user(
        self,
        name: str,
    ) -> dict | None:
        """
        Resolve a human-provided Slack name to a workspace user.

        Matching is performed dynamically against the current
        Slack workspace directory.
        """
        normalized_name = self._normalize(name)
        if not normalized_name:
            return None

        users = self.get_workspace_users()

        exact_matches: list[dict] = []
        partial_matches: list[dict] = []

        for user in users:
            if user.get("deleted"):
                continue

            display_name = self._display_name_from_user(user, fallback="")
            real_name = user.get("real_name", "")
            username = user.get("name", "")

            candidates = {
                self._normalize(display_name),
                self._normalize(real_name),
                self._normalize(username),
            }
            candidates.discard("")

            if normalized_name in candidates:
                exact_matches.append(user)
                continue

            if any(
                normalized_name in candidate or candidate in normalized_name
                for candidate in candidates
            ):
                partial_matches.append(user)

        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            return None
        if len(partial_matches) == 1:
            return partial_matches[0]
        return None

    @staticmethod
    def get_user_id(user: dict | None) -> str | None:
        """
        Extract a Slack user ID from a resolved workspace user.
        """
        if not user:
            return None
        return user.get("id")

    @staticmethod
    def _display_name_from_user(user: dict, fallback: str) -> str:
        profile = user.get("profile", {})
        return (
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("real_name")
            or fallback
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.strip().lower().split())
