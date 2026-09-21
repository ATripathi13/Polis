"""
Slack user identity service.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv


load_dotenv()


class SlackIdentityService:
    """
    Resolves Slack user identities dynamically from the workspace.
    """

    def __init__(self) -> None:
        self._token = os.environ["SLACK_BOT_TOKEN"]

        self._headers = {
            "Authorization": f"Bearer {self._token}",
        }

        self._users_info_url = (
            "https://slack.com/api/users.info"
        )

        self._users_list_url = (
            "https://slack.com/api/users.list"
        )

        self._directory: list[dict] | None = None

    def get_display_name(
        self,
        user_id: str,
    ) -> str:
        """
        Resolve a Slack user ID into a human-readable name.
        """

        response = requests.get(
            self._users_info_url,
            params={
                "user": user_id,
            },
            headers=self._headers,
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get(
                    "error",
                    "Unable to resolve Slack user.",
                )
            )

        user = data.get(
            "user",
            {},
        )

        return self._display_name_from_user(
            user,
            fallback=user_id,
        )

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

        while True:
            params: dict[str, str] = {
                "limit": "200",
            }

            if cursor:
                params["cursor"] = cursor

            response = requests.get(
                self._users_list_url,
                params=params,
                headers=self._headers,
                timeout=10,
            )

            response.raise_for_status()

            data = response.json()

            if not data.get("ok"):
                raise RuntimeError(
                    data.get(
                        "error",
                        "Unable to retrieve Slack workspace users.",
                    )
                )

            users.extend(
                data.get(
                    "members",
                    [],
                )
            )

            cursor = (
                data.get(
                    "response_metadata",
                    {},
                ).get("next_cursor")
                or None
            )

            if not cursor:
                break

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

            display_name = self._display_name_from_user(
                user,
                fallback="",
            )

            real_name = user.get(
                "real_name",
                "",
            )

            username = user.get(
                "name",
                "",
            )

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
                normalized_name in candidate
                or candidate in normalized_name
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
    def get_user_id(
        user: dict | None,
    ) -> str | None:
        """
        Extract a Slack user ID from a resolved workspace user.
        """

        if not user:
            return None

        return user.get("id")

    @staticmethod
    def _display_name_from_user(
        user: dict,
        fallback: str,
    ) -> str:
        profile = user.get(
            "profile",
            {},
        )

        return (
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("real_name")
            or fallback
        )

    @staticmethod
    def _normalize(
        value: str,
    ) -> str:
        return " ".join(
            value.strip().lower().split()
        )