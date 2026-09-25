from __future__ import annotations

from sentence_transformers import SentenceTransformer


class LocalEmbeddingClient:
    """
    Local, free embedding client using BAAI/bge-small-en-v1.5.

    Produces 384-dimensional normalized embeddings.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
    ) -> None:
        self._model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("text cannot be empty.")

        embedding = self._model.encode(
            text,
            normalize_embeddings=True,
        )

        return embedding.tolist()

    def embed_many(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []

        if any(not text.strip() for text in texts):
            raise ValueError(
                "texts cannot contain empty values."
            )

        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
        )

        return [
            embedding.tolist()
            for embedding in embeddings
        ]