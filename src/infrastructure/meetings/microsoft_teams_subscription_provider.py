"""
Microsoft Teams Graph subscription provider.

Creates Microsoft Graph subscriptions for Teams transcript notifications.
"""

from __future__ import annotations

from datetime import datetime

import requests


class MicrosoftTeamsSubscriptionProvider:
    """
    Microsoft Graph implementation for Teams transcript subscriptions.

    Authentication is supplied through an access-token callback so that
    authentication/token acquisition remains separate from subscription
    management.
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

    def create_subscription(
        self,
        *,
        resource: str,
        notification_url: str,
        expiration_datetime: datetime,
        client_state: str,
    ) -> dict:
        access_token = self.access_token_provider()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "changeType": "created",
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration_datetime.isoformat(),
            "clientState": client_state,
        }

        response = requests.post(
            f"{self.GRAPH_BASE_URL}/subscriptions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()
    def renew_subscription(
        self,
        *,
        subscription_id: str,
        expiration_datetime: datetime,
    ) -> dict:
        access_token = self.access_token_provider()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "expirationDateTime": expiration_datetime.isoformat(),
        }

        response = requests.patch(
            (
                f"{self.GRAPH_BASE_URL}"
                f"/subscriptions/{subscription_id}"
            ),
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()