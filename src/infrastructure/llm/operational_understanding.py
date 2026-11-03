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

Determine whether it contains a genuine operational item.

Operational items are:

TASK:
A concrete piece of work that someone needs to do.

DECISION:
A decision that has been made, approved, rejected, or finalized.

RISK:
A problem, blocker, dependency, threat, or potential issue
that may negatively affect work or an outcome.

CRITICAL RULES:
1. Do NOT classify user questions directed to POLIS (e.g., "Can you tell me what you can help me with?", "Can you help me follow up on a pending task?", "What can you do?") as operational items. Return is_operational: false.
2. Do NOT classify conversational acknowledgements, greetings, or casual chatter (e.g., "Ok sir I will check with it", "Thank you", "Got it", "Good morning") as operational items. Return is_operational: false.
3. If an item is an organization-wide announcement, holiday, or calendar entry (e.g., "Add Diwali to company calendar for the whole organization"), set "ownership_type": "organization_wide" and "is_organization_wide": true.
4. If a task is explicitly assigned to a named person (e.g. "Hemant, please prepare the report"), set "ownership_type": "explicit_assignment" and "assignee": "Hemant".
5. If the author explicitly commits to doing the work themselves (e.g. "I will complete the API integration"), set "ownership_type": "self_commitment".
6. If the author mentions delegating to others or multiple people (e.g. "I will instruct Hemant or Vijay to connect PC"), set "ownership_type": "unassigned".

Return ONLY valid JSON in this exact structure:

{{
    "is_operational": true,
    "type": "task",
    "summary": "short canonical statement",
    "confidence": 0.0,
    "ownership_type": "explicit_assignment",
    "assignee": "",
    "is_organization_wide": false
}}

The "type" MUST be exactly one of:
"task", "decision", "risk", "none".

The "ownership_type" MUST be exactly one of:
"explicit_assignment", "self_commitment", "unassigned", "organization_wide".

If there is no operational item, return:

{{
    "is_operational": false,
    "type": "none",
    "summary": "",
    "confidence": 0.0,
    "ownership_type": "unassigned",
    "assignee": "",
    "is_organization_wide": false
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
                "ownership_type": "unassigned",
                "assignee": "",
                "is_organization_wide": False,
            }
