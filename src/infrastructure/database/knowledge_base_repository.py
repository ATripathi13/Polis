from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from domain.knowledge_base import (
    KnowledgeBaseChunk,
    KnowledgeBaseChunkRepository,
    KnowledgeBaseDocument,
    KnowledgeBaseDocumentRepository,
)

from .connection import SessionLocal
from .models import (
    KnowledgeBaseChunkModel,
    KnowledgeBaseDocumentModel,
)


class PostgreSQLKnowledgeBaseDocumentRepository(
    KnowledgeBaseDocumentRepository,
):
    """
    PostgreSQL repository for Knowledge Base documents.
    """

    def save(
        self,
        document: KnowledgeBaseDocument,
    ) -> None:
        with SessionLocal() as session:

            record = session.get(
                KnowledgeBaseDocumentModel,
                document.id,
            )

            if record is None:
                record = KnowledgeBaseDocumentModel(
                    id=document.id,
                    name=document.name,
                    mime_type=document.mime_type,
                    object_key=document.object_key,
                    checksum=document.checksum,
                    status=document.status,
                    created_at=document.created_at,
                    updated_at=document.updated_at,
                    metadata_=document.metadata,
                )

                session.add(record)

            else:
                record.name = document.name
                record.mime_type = document.mime_type
                record.object_key = document.object_key
                record.checksum = document.checksum
                record.status = document.status
                record.updated_at = document.updated_at
                record.metadata_ = document.metadata

            session.commit()

    def find(
        self,
        document_id: str,
    ) -> KnowledgeBaseDocument | None:
        with SessionLocal() as session:

            record = session.get(
                KnowledgeBaseDocumentModel,
                document_id,
            )

            if record is None:
                return None

            return self._to_domain(record)

    def find_by_checksum(
        self,
        checksum: str,
    ) -> KnowledgeBaseDocument | None:
        with SessionLocal() as session:

            record = (
                session.query(
                    KnowledgeBaseDocumentModel
                )
                .filter(
                    KnowledgeBaseDocumentModel.checksum
                    == checksum
                )
                .first()
            )

            if record is None:
                return None

            return self._to_domain(record)

    def all(
        self,
    ) -> list[KnowledgeBaseDocument]:
        with SessionLocal() as session:

            records = (
                session.query(
                    KnowledgeBaseDocumentModel
                )
                .order_by(
                    KnowledgeBaseDocumentModel.created_at
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

    def delete(
        self,
        document_id: str,
    ) -> None:
        with SessionLocal() as session:

            record = session.get(
                KnowledgeBaseDocumentModel,
                document_id,
            )

            if record is None:
                return

            session.delete(record)
            session.commit()

    @staticmethod
    def _to_domain(
        record: KnowledgeBaseDocumentModel,
    ) -> KnowledgeBaseDocument:
        return KnowledgeBaseDocument(
            id=record.id,
            name=record.name,
            mime_type=record.mime_type,
            object_key=record.object_key,
            checksum=record.checksum,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=record.metadata_,
        )


class PostgreSQLKnowledgeBaseChunkRepository(
    KnowledgeBaseChunkRepository,
):
    """
    PostgreSQL repository for Knowledge Base chunks.
    """

    def save(
        self,
        chunk: KnowledgeBaseChunk,
    ) -> None:
        with SessionLocal() as session:

            record = session.get(
                KnowledgeBaseChunkModel,
                chunk.id,
            )

            if record is None:
                record = KnowledgeBaseChunkModel(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    qdrant_point_id=chunk.qdrant_point_id,
                    metadata_=chunk.metadata,
                    created_at=(
                        chunk.created_at
                        or datetime.now(timezone.utc)
                    ),
                )

                session.add(record)

            else:
                record.document_id = chunk.document_id
                record.chunk_index = chunk.chunk_index
                record.content = chunk.content
                record.page_number = chunk.page_number
                record.section_title = chunk.section_title
                record.qdrant_point_id = chunk.qdrant_point_id
                record.metadata_ = chunk.metadata

            session.commit()

    def save_many(
        self,
        chunks: list[KnowledgeBaseChunk],
    ) -> None:
        if not chunks:
            return

        with SessionLocal() as session:

            for chunk in chunks:
                record = session.get(
                    KnowledgeBaseChunkModel,
                    chunk.id,
                )

                if record is None:
                    record = KnowledgeBaseChunkModel(
                        id=chunk.id,
                        document_id=chunk.document_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        page_number=chunk.page_number,
                        section_title=chunk.section_title,
                        qdrant_point_id=chunk.qdrant_point_id,
                        metadata_=chunk.metadata,
                        created_at=(
                            chunk.created_at
                            or datetime.now(timezone.utc)
                        ),
                    )

                    session.add(record)

                else:
                    record.document_id = chunk.document_id
                    record.chunk_index = chunk.chunk_index
                    record.content = chunk.content
                    record.page_number = chunk.page_number
                    record.section_title = chunk.section_title
                    record.qdrant_point_id = chunk.qdrant_point_id
                    record.metadata_ = chunk.metadata

            session.commit()

    def find_by_document(
        self,
        document_id: str,
    ) -> list[KnowledgeBaseChunk]:
        with SessionLocal() as session:

            records = (
                session.query(
                    KnowledgeBaseChunkModel
                )
                .filter(
                    KnowledgeBaseChunkModel.document_id
                    == document_id
                )
                .order_by(
                    KnowledgeBaseChunkModel.chunk_index
                )
                .all()
            )

            return [
                self._to_domain(record)
                for record in records
            ]

    def delete_by_document(
        self,
        document_id: str,
    ) -> None:
        with SessionLocal() as session:

            (
                session.query(
                    KnowledgeBaseChunkModel
                )
                .filter(
                    KnowledgeBaseChunkModel.document_id
                    == document_id
                )
                .delete(
                    synchronize_session=False
                )
            )

            session.commit()

    @staticmethod
    def _to_domain(
        record: KnowledgeBaseChunkModel,
    ) -> KnowledgeBaseChunk:
        return KnowledgeBaseChunk(
            id=record.id,
            document_id=record.document_id,
            chunk_index=record.chunk_index,
            content=record.content,
            page_number=record.page_number,
            section_title=record.section_title,
            qdrant_point_id=record.qdrant_point_id,
            metadata=record.metadata_,
            created_at=record.created_at,
        )