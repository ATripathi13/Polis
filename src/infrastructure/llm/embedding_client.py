from __future__ import annotations

from openai import OpenAI

from infrastructure.config.settings import get_settings


class OpenRouterEmbeddingClient:
    """
    Infrastructure adapter for generating Knowledge Base embeddings.
    """

    def __init__(self) -> None:
        settings = get_settings()

        self._client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )

        self._model = (
            settings.knowledge_base_embedding_model
        )

    def embed(
        self,
        text: str,
    ) -> list[float]:
        """
        Generate one embedding vector for the supplied text.
        """

        if not text.strip():
            raise ValueError(
                "text cannot be empty."
            )

        response = self._client.embeddings.create(
            model=self._model,
            input=text,
        )

        embedding = response.data[0].embedding

        if len(embedding) != 1536:
            raise ValueError(
                "Unexpected embedding dimension: "
                f"{len(embedding)}"
            )

        return embedding

    def embed_many(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in one API call.
        """

        if not texts:
            return []

        if any(
            not text.strip()
            for text in texts
        ):
            raise ValueError(
                "texts cannot contain empty values."
            )

        response = self._client.embeddings.create(
            model=self._model,
            input=texts,
        )

        embeddings = [
            item.embedding
            for item in response.data
        ]

        if len(embeddings) != len(texts):
            raise ValueError(
                "Embedding response count does not match "
                "input count."
            )

        if any(
            len(embedding) != 1536
            for embedding in embeddings
        ):
            raise ValueError(
                "Unexpected embedding dimension."
            )

        return embeddings