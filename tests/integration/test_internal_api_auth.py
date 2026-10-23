from fastapi.testclient import TestClient

from infrastructure.config.settings import get_settings
from interfaces.api.app import app


client = TestClient(app)
ASK_ENDPOINTS = [
    "/ask",
    "/ask/knowledge",
    "/ask/operations",
    "/ask/governance",
]
PAYLOAD = {"question": "What decisions are pending?"}


def test_ask_endpoints_reject_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        get_settings(),
        "polis_api_key",
        "test-internal-key",
    )

    for endpoint in ASK_ENDPOINTS:
        response = client.post(endpoint, json=PAYLOAD)
        assert response.status_code == 401, (
            f"{endpoint} accepted a request without an API key"
        )


def test_ask_endpoints_reject_invalid_api_key(monkeypatch):
    monkeypatch.setattr(
        get_settings(),
        "polis_api_key",
        "test-internal-key",
    )

    for endpoint in ASK_ENDPOINTS:
        response = client.post(
            endpoint,
            json=PAYLOAD,
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401, (
            f"{endpoint} accepted an invalid API key"
        )


def test_ask_endpoints_accept_valid_api_key(monkeypatch):
    monkeypatch.setattr(
        get_settings(),
        "polis_api_key",
        "test-internal-key",
    )

    for endpoint in ASK_ENDPOINTS:
        response = client.post(
            endpoint,
            json=PAYLOAD,
            headers={"X-API-Key": "test-internal-key"},
        )
        assert response.status_code != 401, (
            f"{endpoint} rejected a valid API key"
        )
