"""
Slack user identity service.
"""

from __future__ import annotations

import requests

from dotenv import load_dotenv

import os


load_dotenv()


class SlackIdentityService:
    """
    Resolves Slack user IDs into human-readable names.
    """

    def __init__(
        self,
    ) -> None:

        self._token = os.environ[
            "SLACK_BOT_TOKEN"
        ]

        self._url = (
            "https://slack.com/api/users.info"
        )

    def get_display_name(
        self,
        user_id: str,
    ) -> str:

        headers = {
            "Authorization": (
                f"Bearer {self._token}"
            ),
        }

        response = requests.get(
            self._url,
            params={
                "user": user_id,
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
                    "Unable to resolve Slack user.",
                )
            )

        user = data.get(
            "user",
            {},
        )

        profile = user.get(
            "profile",
            {},
        )

        return (
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("real_name")
            or user_id
        )