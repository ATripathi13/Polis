"""
Microsoft Teams recording provider.

Retrieves Teams meeting recordings through Microsoft Graph.
"""

from __future__ import annotations

from datetime import datetime

import requests

from application.meetings.meeting_recording_input import (
    MeetingRecordingInput,
)
from application.meetings.meeting_recording_provider import (
    MeetingRecordingProvider,
)


class MicrosoftTeamsRecordingProvider(MeetingRecordingProvider):
    """
    Microsoft Graph implementation of the meeting recording provider.

    Authentication is supplied through an access-token callback so that
    authentication/token acquisition remains separate from recording
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

    def get_recording_by_notification(
        self,
        *,
        user_id: str,
        online_meeting_id: str,
        recording_id: str,
    ) -> MeetingRecordingInput | None:

        access_token = self.access_token_provider()

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        content_url = (
            f"{self.GRAPH_BASE_URL}"
            f"/users/{user_id}"
            f"/onlineMeetings/{online_meeting_id}"
            f"/recordings/{recording_id}/content"
        )

        response = requests.get(
            content_url,
            headers=headers,
            timeout=self.timeout,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        content = response.content

        if not content:
            return None

        content_type = response.headers.get(
            "Content-Type",
            "video/mp4",
        )

        return MeetingRecordingInput(
            meeting_id=online_meeting_id,
            content=content,
            source="Microsoft Teams",
            captured_at=datetime.now().astimezone(),
            content_type=content_type,
            metadata={
                "provider": "microsoft_graph",
                "user_id": user_id,
                "online_meeting_id": online_meeting_id,
                "recording_id": recording_id,
            },
        )
