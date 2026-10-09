from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_meeting_intelligence_service


def test_meeting_summary_endpoint():
    app.dependency_overrides[get_meeting_intelligence_service] = lambda: SimpleNamespace(
        summarize=lambda meeting_id: SimpleNamespace(
            text=f"Test summary for {meeting_id}",
        ),
    )

    try:
        response = TestClient(app).get(
            "/meetings/test-meeting-123/summary"
        )

        assert response.status_code == 200
        assert response.json() == {
            "answer": "Test summary for test-meeting-123",
        }
    finally:
        app.dependency_overrides.pop(
            get_meeting_intelligence_service,
            None,
        )
