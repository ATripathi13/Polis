from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.knowledge_base import (
    KnowledgeBaseChunk,
    KnowledgeBaseChunkRepository,
    KnowledgeBaseDocument,
    KnowledgeBaseDocumentRepository,
    KnowledgeBaseObjectStorage,
    KnowledgeBaseVectorRepository,
)

from infrastructure.documents import (
    DocumentChunker,
    DocumentParser,
)

from infrastructure.llm import (
    OpenRouterEmbeddingClient,
)


class KnowledgeBaseIngestionService:
    """
    Ingests source documents into the POLIS Knowledge Base.

    Flow:
        file
        -> checksum
        -> object storage
        -> parsing
        -> chunking
        -> embeddings
        -> PostgreSQL
        -> Qdrant
    """

    READY = "READY"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"

    def __init__(
        self,
        *,
        document_repository: KnowledgeBaseDocumentRepository,
        chunk_repository: KnowledgeBaseChunkRepository,
        vector_repository: KnowledgeBaseVectorRepository,
        object_storage: KnowledgeBaseObjectStorage,
        parser: DocumentParser,
        chunker: DocumentChunker,
        embedding_client: OpenRouterEmbeddingClient,
    ) -> None:
        self._document_repository = document_repository
        self._chunk_repository = chunk_repository
        self._vector_repository = vector_repository
        self._object_storage = object_storage
        self._parser = parser
        self._chunker = chunker
        self._embedding_client = embedding_client

    def ingest(
        self,
        path: Path,
        *,
        name: str | None = None,
        mime_type: str,
    ) -> KnowledgeBaseDocument:
        """
        Ingest one document into the Knowledge Base.
        """

        if not path.exists():
            raise FileNotFoundError(path)

        data = path.read_bytes()

        if not data:
            raise ValueError(
                "Document cannot be empty."
            )

        checksum = hashlib.sha256(
            data
        ).hexdigest()

        existing = (
            self._document_repository.find_by_checksum(
                checksum
            )
        )

        if existing is not None:
            if existing.status == self.READY:
                return existing

            self._document_repository.delete(
                existing.id
            )
        document_id = str(uuid4())

        document_name = (
            name
            or path.name
        )

        object_key = (
            f"documents/"
            f"{document_id}/"
            f"{document_name}"
        )

        now = datetime.now(timezone.utc)

        document = KnowledgeBaseDocument(
            id=document_id,
            name=document_name,
            mime_type=mime_type,
            object_key=object_key,
            checksum=checksum,
            status=self.PROCESSING,
            created_at=now,
            updated_at=now,
        )

        self._document_repository.save(
            document
        )

        try:
            self._object_storage.put(
                object_key,
                data,
                content_type=mime_type,
            )

            sections = self._parser.parse(
                path,
                mime_type,
            )

            chunks = self._chunker.chunk(
                sections
            )

            if not chunks:
                raise ValueError(
                    "No readable text was extracted "
                    "from the document."
                )

            domain_chunks: list[
                KnowledgeBaseChunk
            ] = []

            for index, chunk in enumerate(chunks):
                chunk_id = str(uuid4())
                qdrant_point_id = str(uuid4())

                domain_chunks.append(
                    KnowledgeBaseChunk(
                        id=chunk_id,
                        document_id=document_id,
                        chunk_index=index,
                        content=chunk.content,
                        page_number=chunk.page_number,
                        section_title=chunk.section_title,
                        qdrant_point_id=qdrant_point_id,
                        metadata={
                            "document_name": document_name,
                            "mime_type": mime_type,
                        },
                        created_at=now,
                    )
                )

            embeddings: list[list[float]] = []

            embedding_batch_size = 25

            for start in range(
                0,
                len(domain_chunks),
                embedding_batch_size,
            ):
                batch = domain_chunks[
                    start:start + embedding_batch_size
                ]

                batch_embeddings = (
                    self._embedding_client.embed_many(
                        [
                            chunk.content
                            for chunk in batch
                        ]
                    )
                )

                embeddings.extend(
                    batch_embeddings
                )

            self._chunk_repository.save_many(
                domain_chunks
            )

            self._vector_repository.upsert_many(
                domain_chunks,
                embeddings,
            )

            ready = KnowledgeBaseDocument(
                id=document.id,
                name=document.name,
                mime_type=document.mime_type,
                object_key=document.object_key,
                checksum=document.checksum,
                status=self.READY,
                created_at=document.created_at,
                updated_at=datetime.now(
                    timezone.utc
                ),
                metadata=document.metadata,
            )

            self._document_repository.save(
                ready
            )

            return ready

        except Exception:
            # Remove any partial vector/database state.
            self._vector_repository.delete_by_document(
                document_id
            )

            self._chunk_repository.delete_by_document(
                document_id
            )

            self._object_storage.delete(
                object_key
            )

            failed = KnowledgeBaseDocument(
                id=document.id,
                name=document.name,
                mime_type=document.mime_type,
                object_key=document.object_key,
                checksum=document.checksum,
                status=self.FAILED,
                created_at=document.created_at,
                updated_at=datetime.now(
                    timezone.utc
                ),
                metadata=document.metadata,
            )

            self._document_repository.save(
                failed
            )

            raise