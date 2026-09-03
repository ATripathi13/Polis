from __future__ import annotations

import json

from infrastructure.llm import OpenRouterClient


class LLMKnowledgeUnderstanding:

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
You are the knowledge understanding component of POLIS,
an organizational memory system.

Analyze the following workplace message.

Determine whether the message contains useful organizational
knowledge that POLIS should remember.

Organizational knowledge can include things such as:

- tools or software the organization uses
- technical processes
- workflows
- decisions
- policies
- procedures
- responsibilities
- project information
- operational facts
- team practices
- infrastructure
- systems
- preferences
- important facts shared by employees

Do NOT require any specific wording such as "we use",
"we have", "our", etc.

Understand the semantic meaning of the message.

Return ONLY valid JSON in this exact structure:

{{
    "is_knowledge": true,
    "summary": "short canonical statement of the knowledge",
    "confidence": 0.0,
    "subject": "main subject of the knowledge"
}}

If the message does not contain useful organizational knowledge,
return:

{{
    "is_knowledge": false,
    "summary": "",
    "confidence": 0.0,
    "subject": ""
}}

Message:

{text}
"""

        response = self._client.generate(prompt)

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {
                "is_knowledge": False,
                "summary": "",
                "confidence": 0.0,
                "subject": "",
            }