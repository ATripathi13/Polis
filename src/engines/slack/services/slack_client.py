"""
Slack Web API client.
"""

from __future__ import annotations

import os

import requests

from dotenv import load_dotenv

load_dotenv()

class SlackClient:
    """
    Simple client for the Slack Web API.
    """
    def __init__(self) -> None:

        self._token = os.environ["SLACK_BOT_TOKEN"]

        self._url = (
            "https://slack.com/api/chat.postMessage"
        )
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
        print("=" * 80)
        print("SLACK API RESPONSE")
        print(response.status_code)
        print(response.json())
        print("=" * 80)
        data = response.json()
        if not data.get("ok"):

            raise RuntimeError(
                data.get(
                    "error",
                    "Unknown Slack error",
                )
            )
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