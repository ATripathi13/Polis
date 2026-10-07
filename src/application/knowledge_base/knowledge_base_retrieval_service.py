from __future__ import annotations

from infrastructure.llm import (
    OpenRouterEmbeddingClient,
)

from domain.knowledge_base import (
    KnowledgeBaseChunk,
    KnowledgeBaseVectorRepository,
)


class KnowledgeBaseRetrievalService:
    """
    Retrieves the most relevant Knowledge Base chunks
    for a natural-language question.
    """

    _MIN_CANDIDATE_LIMIT = 15
    _CANDIDATE_MULTIPLIER = 3
    _CURRENT_AUTHORITY_BONUS = 0.03

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
        employee_slack_user_id: str | None = None,
    ) -> list[tuple[KnowledgeBaseChunk, float]]:
        """
        Convert the question into an embedding, retrieve a broader
        semantic candidate set, and apply lightweight authority-aware
        reranking before returning the requested number of results.
        """

        if not question.strip():
            return []

        embedding = self._embedding_client.embed(
            question
        )

        candidate_limit = max(
            limit * self._CANDIDATE_MULTIPLIER,
            self._MIN_CANDIDATE_LIMIT,
        )

        candidates = self._vector_repository.search(
            embedding,
            limit=candidate_limit,
            document_id=document_id,
            employee_slack_user_id=employee_slack_user_id,
        )

        reranked = sorted(
            candidates,
            key=self._ranking_score,
            reverse=True,
        )

        return reranked[:limit]

    @classmethod
    def _ranking_score(
        cls,
        result: tuple[KnowledgeBaseChunk, float],
    ) -> float:
        chunk, semantic_score = result

        authority = chunk.metadata.get("authority")

        if (
            isinstance(authority, str)
            and authority.startswith("current_")
        ):
            return semantic_score + cls._CURRENT_AUTHORITY_BONUS

        return semantic_score
