from fastapi.testclient import TestClient

from api.app import app


client = TestClient(app)


def test_slack_event_endpoint():

    payload = {
        "user": {
            "user_id": "U123",
            "username": "john",
        },
        "channel": {
            "channel_id": "C123",
            "name": "general",
        },
        "message": {
            "text": "Hello Polis!",
            "ts": "1712345678.123456",
        },
    }

    response = client.post(
        "/connectors/slack/events",
        json=payload,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "success"
    assert data["correlation_id"] == "1712345678.123456"
    assert data["source"] == "slack"