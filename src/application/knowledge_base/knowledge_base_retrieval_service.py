from __future__ import annotations

from infrastructure.llm import (
    OpenRouterEmbeddingClient,
)

from domain.knowledge_base import (
    KnowledgeBaseVectorRepository,
)


class KnowledgeBaseRetrievalService:
    """
    Retrieves the most relevant Knowledge Base chunks
    for a natural-language question.
    """

    def __init__(
        self,
        *,
        vector_repository: KnowledgeBaseVectorRepository,
        embedding_client: OpenRouterEmbeddingClient,
    ) -> None:
        self._vector_repository = vector_repository
        self._embedding_client = embedding_client

    def retrieve(
        self,
        question: str,
        *,
        limit: int = 5,
        document_id: str | None = None,
    ):
        """
        Convert the question into an embedding and retrieve
        the most semantically relevant Knowledge Base chunks.
        """

        if not question.strip():
            return []

        embedding = self._embedding_client.embed(
            question
        )

        return self._vector_repository.search(
            embedding,
            limit=limit,
            document_id=document_id,
        )