from __future__ import annotations

from openai import OpenAI

from infrastructure.config.settings import get_settings


class OpenRouterClient:
    """
    Infrastructure adapter for OpenRouter.

    POLIS application/domain code should not
    directly depend on the OpenRouter SDK.
    """

    def __init__(self) -> None:

        settings = get_settings()

        self._client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )

        self._model = settings.openrouter_model

    def generate(
        self,
        prompt: str,
    ) -> str:

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        return response.choices[0].message.content or ""