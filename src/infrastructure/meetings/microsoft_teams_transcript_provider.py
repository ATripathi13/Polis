"""
Microsoft Teams transcript provider.

Retrieves Teams meeting transcripts through Microsoft Graph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from application.meetings.meeting_transcript_input import (
    MeetingTranscriptInput,
)
from application.meetings.meeting_transcript_provider import (
    MeetingTranscriptProvider,
)


class MicrosoftTeamsTranscriptProvider(MeetingTranscriptProvider):
    """
    Microsoft Graph implementation of the meeting transcript provider.

    Authentication is supplied through an access-token callback so that
    authentication/token acquisition remains separate from transcript
    retrieval.
    """

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        access_token_provider,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.access_token_provider = access_token_provider
        self.timeout = timeout

    def get_transcript(
        self,
        meeting_id: str,
    ) -> MeetingTranscriptInput | None:

        access_token = self.access_token_provider()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "text/vtt",
        }

        transcripts_url = (
            f"{self.GRAPH_BASE_URL}"
            f"/communications/onlineMeetings/"
            f"{meeting_id}/transcripts"
        )

        response = requests.get(
            transcripts_url,
            headers=headers,
            timeout=self.timeout,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        data = response.json()
        values = data.get("value", [])

        if not values:
            return None

        transcript_record = values[0]

        transcript_id = transcript_record.get("id")

        if not transcript_id:
            return None

        content_url = (
            f"{self.GRAPH_BASE_URL}"
            f"/communications/onlineMeetings/"
            f"{meeting_id}/transcripts/"
            f"{transcript_id}/content"
        )

        content_response = requests.get(
            content_url,
            headers=headers,
            timeout=self.timeout,
        )

        content_response.raise_for_status()

        transcript_text = content_response.text.strip()

        if not transcript_text:
            return None

        captured_at = self._parse_datetime(
            transcript_record.get("createdDateTime")
        )

        if captured_at is None:
            captured_at = datetime.now().astimezone()

        return MeetingTranscriptInput(
            meeting_id=meeting_id,
            transcript=transcript_text,
            source="Microsoft Teams",
            captured_at=captured_at,
            participants=[],
            metadata={
                "provider": "microsoft_graph",
                "transcript_id": transcript_id,
            },
        )
    def get_transcript_by_notification(
        self,
        *,
        user_id: str,
        online_meeting_id: str,
        transcript_id: str,
    ) -> MeetingTranscriptInput | None:
        """
        Retrieve a specific Teams transcript identified by
        a Microsoft Graph transcript notification.
        """

        access_token = self.access_token_provider()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "text/vtt",
        }

        content_url = (
            f"{self.GRAPH_BASE_URL}"
            f"/users/{user_id}"
            f"/onlineMeetings/{online_meeting_id}"
            f"/transcripts/{transcript_id}/content"
        )

        response = requests.get(
            content_url,
            headers=headers,
            timeout=self.timeout,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        transcript_text = response.text.strip()

        if not transcript_text:
            return None

        return MeetingTranscriptInput(
            meeting_id=online_meeting_id,
            transcript=transcript_text,
            source="Microsoft Teams",
            captured_at=datetime.now().astimezone(),
            participants=[],
            metadata={
                "provider": "microsoft_graph",
                "user_id": user_id,
                "online_meeting_id": online_meeting_id,
                "transcript_id": transcript_id,
            },
        )
    @staticmethod
    def _parse_datetime(
        value: str | None,
    ) -> datetime | None:

        if not value:
            return None

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            return None