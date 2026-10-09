from __future__ import annotations

import json

from infrastructure.llm import OpenRouterClient


class LLMOrganizationalIntentUnderstanding:
    """
    Identifies organizational intents that are not covered by
    the existing question, knowledge, or operational analyzers.
    """

    def __init__(
        self,
        client: OpenRouterClient,
    ) -> None:
        self._client = client

    def analyze(
        self,
        text: str,
    ) -> dict:

        prompt = f"""
You are the organizational intent understanding component of POLIS,
an organizational intelligence system.

Analyze the following workplace communication.

Identify whether the message contains one of these organizational intents:

APPROVAL:
An explicit statement that a requested action, change, or decision has
been approved, authorized, accepted, or given permission.

Do NOT classify an approval request as APPROVAL. A request for approval
is only a request and must not produce an APPROVAL intent.

CONTRADICTION:
A meaningful conflict between statements, facts, commitments, or decisions
within the communication.

POLICY_VIOLATION:
A statement indicating that an organizational policy, rule, procedure,
or compliance requirement has been violated or is being violated.

SUMMARY_REQUEST:
A request for a summary, recap, synthesis, or condensed explanation
of organizational information.

Do NOT classify the following here:
- questions
- organizational knowledge
- tasks
- decisions
- risks
- greetings
- casual conversation
- generic status updates
- requests that merely ask someone to perform work

Only identify an intent when the semantic meaning clearly supports it.

Return ONLY valid JSON in this exact structure:

{{
    "is_intent": true,
    "type": "approval",
    "summary": "short canonical statement",
    "confidence": 0.0
}}

The "type" MUST be exactly one of:
"approval", "contradiction", "policy_violation",
"summary_request", "none".

If none of these intents apply, return:

{{
    "is_intent": false,
    "type": "none",
    "summary": "",
    "confidence": 0.0
}}

Communication:

{text}
"""

        response = self._client.generate(prompt)

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            return {
                "is_intent": False,
                "type": "none",
                "summary": "",
                "confidence": 0.0,
            }

        return result
