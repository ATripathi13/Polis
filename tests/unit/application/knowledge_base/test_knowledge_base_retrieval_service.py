from unittest.mock import MagicMock

from application.knowledge_base.knowledge_base_retrieval_service import (
    KnowledgeBaseRetrievalService,
)
from domain.knowledge_base import KnowledgeBaseChunk


def make_chunk(
    *,
    document_name: str,
    authority: str | None = None,
) -> KnowledgeBaseChunk:
    metadata = {}

    if authority is not None:
        metadata["authority"] = authority

    return KnowledgeBaseChunk(
        id=f"{document_name}-chunk",
        document_id=f"{document_name}-document",
        chunk_index=0,
        content=f"Content from {document_name}",
        qdrant_point_id=f"{document_name}-point",
        metadata=metadata,
    )


def make_service(results):
    vector_repository = MagicMock()
    vector_repository.search.return_value = results

    embedding_client = MagicMock()
    embedding_client.embed.return_value = [0.1, 0.2, 0.3]

    service = KnowledgeBaseRetrievalService(
        vector_repository=vector_repository,
        embedding_client=embedding_client,
    )

    return service, vector_repository, embedding_client


def test_current_authoritative_source_can_outrank_nearly_equal_published_source():
    published = make_chunk(
        document_name="8 website.md",
        authority="published_source",
    )
    strategy = make_chunk(
        document_name="04 digital_transformation.md",
        authority="current_strategy",
    )

    results = [
        (published, 0.8100),
        (strategy, 0.7818),
    ]

    service, vector_repository, _ = make_service(results)

    retrieved = service.retrieve(
        "How should an organization approach digital transformation?"
    )

    assert retrieved[0][0].document_id == strategy.document_id
    assert retrieved[1][0].document_id == published.document_id

    vector_repository.search.assert_called_once()

    search_kwargs = vector_repository.search.call_args.kwargs
    assert search_kwargs["limit"] >= 15


def test_clear_semantic_winner_is_not_overridden_by_authority_bonus():
    published = make_chunk(
        document_name="8 website.md",
        authority="published_source",
    )
    strategy = make_chunk(
        document_name="04 digital_transformation.md",
        authority="current_strategy",
    )

    results = [
        (published, 0.9500),
        (strategy, 0.8100),
    ]

    service, _, _ = make_service(results)

    retrieved = service.retrieve(
        "What is the exact content published on the website?"
    )

    assert retrieved[0][0].document_id == published.document_id
    assert retrieved[1][0].document_id == strategy.document_id


def test_existing_filters_are_forwarded_unchanged():
    strategy = make_chunk(
        document_name="04 digital_transformation.md",
        authority="current_strategy",
    )

    service, vector_repository, _ = make_service(
        [(strategy, 0.8)]
    )

    service.retrieve(
        "digital transformation",
        limit=3,
        document_id="document-123",
        employee_slack_user_id="user-456",
    )

    vector_repository.search.assert_called_once()

    args, kwargs = vector_repository.search.call_args

    assert kwargs["limit"] >= 15
    assert kwargs["document_id"] == "document-123"
    assert kwargs["employee_slack_user_id"] == "user-456"
