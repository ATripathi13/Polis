from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from domain.knowledge_base import (
    KnowledgeBaseChunk,
    KnowledgeBaseVectorRepository,
)

from infrastructure.config.settings import get_settings


class QdrantKnowledgeBaseRepository(
    KnowledgeBaseVectorRepository,
):
    """
    Qdrant adapter for Knowledge Base semantic search.
    """

    COLLECTION_NAME = "polis_knowledge_base_bge_small"
    VECTOR_SIZE = 384

    def __init__(self) -> None:
        settings = get_settings()

        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        collections = self._client.get_collections()

        exists = any(
            collection.name == self.COLLECTION_NAME
            for collection in collections.collections
        )

        if exists:
            return

        self._client.create_collection(
            collection_name=self.COLLECTION_NAME,
            vectors_config=VectorParams(
                size=self.VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )

    def upsert(
        self,
        chunk: KnowledgeBaseChunk,
        embedding: list[float],
    ) -> None:
        self._validate_embedding(embedding)

        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[
                self._point(
                    chunk,
                    embedding,
                )
            ],
            wait=True,
        )

    def upsert_many(
        self,
        chunks: list[KnowledgeBaseChunk],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(
                "chunks and embeddings must have the same length."
            )

        if not chunks:
            return

        points = []

        for chunk, embedding in zip(
            chunks,
            embeddings,
            strict=True,
        ):
            self._validate_embedding(embedding)

            points.append(
                self._point(
                    chunk,
                    embedding,
                )
            )

        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=points,
            wait=True,
        )

    def delete_by_document(
        self,
        document_id: str,
    ) -> None:
        self._client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(
                            value=document_id,
                        ),
                    )
                ]
            ),
            wait=True,
        )

    def search(
        self,
        embedding: list[float],
        *,
        limit: int = 5,
        document_id: str | None = None,
    ) -> list[tuple[KnowledgeBaseChunk, float]]:
        self._validate_embedding(embedding)

        query_filter = None

        if document_id is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(
                            value=document_id,
                        ),
                    )
                ]
            )

        response = self._client.query_points(
            collection_name=self.COLLECTION_NAME,
            query=embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        results: list[tuple[KnowledgeBaseChunk, float]] = []

        for point in response.points:
            payload = point.payload or {}

            chunk = KnowledgeBaseChunk(
                id=str(payload["chunk_id"]),
                document_id=str(payload["document_id"]),
                chunk_index=int(payload["chunk_index"]),
                content=str(payload["content"]),
                page_number=(
                    int(payload["page_number"])
                    if payload.get("page_number") is not None
                    else None
                ),
                section_title=(
                    str(payload["section_title"])
                    if payload.get("section_title") is not None
                    else None
                ),
                qdrant_point_id=str(point.id),
                metadata=payload.get("metadata", {}),
            )

            results.append(
                (
                    chunk,
                    float(point.score),
                )
            )

        return results

    @staticmethod
    def _validate_embedding(
        embedding: list[float],
    ) -> None:
        if len(embedding) != 384:
            raise ValueError(
                "Knowledge Base embeddings must contain "
                "384 dimensions."
            )

    @staticmethod
    def _point(
        chunk: KnowledgeBaseChunk,
        embedding: list[float],
    ) -> PointStruct:
        return PointStruct(
            id=chunk.qdrant_point_id,
            vector=embedding,
            payload={
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "page_number": chunk.page_number,
                "section_title": chunk.section_title,
                "metadata": chunk.metadata,
            },
        )
