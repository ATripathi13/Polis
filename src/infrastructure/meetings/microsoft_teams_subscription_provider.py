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

    @staticmethod
    def _raise_for_graph_error(response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            try:
                error = response.json().get("error", {})
                code = error.get("code", "Unknown")
                message = error.get("message", "No error message provided")
            except (ValueError, AttributeError, TypeError):
                code = "Unknown"
                message = "Microsoft Graph returned a non-JSON error response"

            raise requests.HTTPError(
                f"Microsoft Graph request failed "
                f"(HTTP {response.status_code}, {code}): {message}",
                response=response,
            ) from exc

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

        self._raise_for_graph_error(response)

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

        self._raise_for_graph_error(response)

        return response.json()
