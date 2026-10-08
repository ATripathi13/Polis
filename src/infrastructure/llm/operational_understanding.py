from __future__ import annotations

import json

from infrastructure.llm import OpenRouterClient


class LLMOperationalUnderstanding:

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
You are the operational understanding component of POLIS,
an organizational intelligence system.

Analyze the following workplace communication.

Determine whether it contains an operational item.

Operational items are:

TASK:
A concrete piece of work that someone needs to do.

DECISION:
A decision that has been made, approved, rejected, or finalized.

RISK:
A problem, blocker, dependency, threat, or potential issue
that may negatively affect work or an outcome.

Do NOT classify general knowledge, questions, greetings,
status updates without an action, or casual conversation
as an operational item.

Return ONLY valid JSON in this exact structure:

{{
    "is_operational": true,
    "type": "task",
    "summary": "short canonical statement",
    "confidence": 0.0
}}

The "type" MUST be exactly one of:
"task", "decision", "risk", "none".

If there is no operational item, return:

{{
    "is_operational": false,
    "type": "none",
    "summary": "",
    "confidence": 0.0
}}

Communication:

{text}
"""

        response = self._client.generate(prompt)

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {
                "is_operational": False,
                "type": "none",
                "summary": "",
                "confidence": 0.0,
            }
