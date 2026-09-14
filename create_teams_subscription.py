from datetime import datetime, timedelta, timezone

import requests

from infrastructure.meetings.microsoft_graph_token_provider import (
    MicrosoftGraphTokenProvider,
)

WEBHOOK_URL = (
    "https://vacant-danger-barman.ngrok-free.dev"
    "/teams/webhook"
)

GRAPH_URL = "https://graph.microsoft.com/v1.0/subscriptions"

token = MicrosoftGraphTokenProvider()()

expires_at = datetime.now(timezone.utc) + timedelta(minutes=55)

payload = {
    "changeType": "created",
    "notificationUrl": WEBHOOK_URL,
    "resource": "communications/onlineMeetings/getAllTranscripts",
    "expirationDateTime": expires_at.isoformat(),
    "clientState": "polis-teams-transcript",
}

response = requests.post(
    GRAPH_URL,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=30,
)

print("STATUS:", response.status_code)
print(response.text)