from infrastructure.llm.organizational_intent_understanding import (
    LLMOrganizationalIntentUnderstanding,
)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt):
        self.last_prompt = prompt
        return self.response


def test_analyze_returns_organizational_intent():
    client = FakeClient(
        '{"is_intent": true, "type": "approval", "summary": "Deployment approved.", "confidence": 0.95}'
    )

    understanding = LLMOrganizationalIntentUnderstanding(client)

    result = understanding.analyze(
        "Approved. Go ahead with the deployment."
    )

    assert result == {
        "is_intent": True,
        "type": "approval",
        "summary": "Deployment approved.",
        "confidence": 0.95,
    }

    assert (
        "Approved. Go ahead with the deployment."
        in client.last_prompt
    )


def test_analyze_handles_invalid_json():
    client = FakeClient("not valid json")

    understanding = LLMOrganizationalIntentUnderstanding(client)

    result = understanding.analyze(
        "Please summarize the meeting."
    )

    assert result == {
        "is_intent": False,
        "type": "none",
        "summary": "",
        "confidence": 0.0,
    }
