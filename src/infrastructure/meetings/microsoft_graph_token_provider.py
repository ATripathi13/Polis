"""
Microsoft Graph access-token provider.
"""

from __future__ import annotations

import msal

from infrastructure.config.settings import get_settings


class MicrosoftGraphTokenProvider:
    """
    Acquires Microsoft Graph application tokens using
    the OAuth 2.0 client-credentials flow.
    """

    GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

    def __init__(self) -> None:
        settings = get_settings()

        self._client = msal.ConfidentialClientApplication(
            client_id=settings.microsoft_graph_client_id,
            client_credential=settings.microsoft_graph_client_secret,
            authority=(
                f"https://login.microsoftonline.com/"
                f"{settings.microsoft_graph_tenant_id}"
            ),
        )

    def __call__(self) -> str:
        result = self._client.acquire_token_for_client(
            scopes=self.GRAPH_SCOPE,
        )

        access_token = result.get("access_token")

        if not access_token:
            error = result.get("error", "unknown_error")
            description = result.get(
                "error_description",
                "No error description provided.",
            )

            raise RuntimeError(
                f"Microsoft Graph token acquisition failed: "
                f"{error}: {description}"
            )

        return access_token