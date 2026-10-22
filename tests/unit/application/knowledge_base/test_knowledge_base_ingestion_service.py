"""
Unit tests for KnowledgeBaseIngestionService verifying document lifecycle,
duplicate detection, metadata classification, rollback on failure, and error handling.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from application.knowledge_base.knowledge_base_ingestion_service import (
    KnowledgeBaseIngestionService,
)
from domain.knowledge_base import (
    KnowledgeBaseDocument,
    KnowledgeBaseChunk,
)


def _setup_service():
    doc_repo = MagicMock()
    chunk_repo = MagicMock()
    vec_repo = MagicMock()
    obj_storage = MagicMock()
    parser = MagicMock()
    chunker = MagicMock()
    embedder = MagicMock()

    service = KnowledgeBaseIngestionService(
        document_repository=doc_repo,
        chunk_repository=chunk_repo,
        vector_repository=vec_repo,
        object_storage=obj_storage,
        parser=parser,
        chunker=chunker,
        embedding_client=embedder,
    )
    return service, doc_repo, chunk_repo, vec_repo, obj_storage, parser, chunker, embedder


def test_ingest_nonexistent_file(tmp_path: Path):
    service, *_ = _setup_service()
    with pytest.raises(FileNotFoundError):
        service.ingest(tmp_path / "not_there.md", mime_type="text/markdown")


def test_ingest_empty_file(tmp_path: Path):
    service, *_ = _setup_service()
    empty_file = tmp_path / "empty.txt"
    empty_file.write_bytes(b"")

    with pytest.raises(ValueError, match="Document cannot be empty"):
        service.ingest(empty_file, mime_type="text/plain")


def test_ingest_no_readable_text(tmp_path: Path):
    service, doc_repo, chunk_repo, vec_repo, obj_storage, parser, chunker, embedder = _setup_service()

    file_path = tmp_path / "blank.pdf"
    file_path.write_bytes(b"%PDF-1.4 dummy non-empty bytes")

    doc_repo.find_by_checksum.return_value = None
    parser.parse.return_value = []
    chunker.chunk.return_value = []

    with pytest.raises(ValueError, match="No readable text was extracted"):
        service.ingest(file_path, mime_type="application/pdf")

    # Rollback assertions
    vec_repo.delete_by_document.assert_called_once()
    chunk_repo.delete_by_document.assert_called_once()
    obj_storage.delete.assert_called_once()
    # Final saved status should be FAILED
    saved_doc = doc_repo.save.call_args.args[0]
    assert saved_doc.status == "FAILED"


def test_ingest_success_flow(tmp_path: Path):
    service, doc_repo, chunk_repo, vec_repo, obj_storage, parser, chunker, embedder = _setup_service()

    file_path = tmp_path / "standard.md"
    file_path.write_text("Valid markdown content for knowledge base.", encoding="utf-8")

    doc_repo.find_by_checksum.return_value = None

    parsed_section = MagicMock(content="Valid markdown content for knowledge base.", page_number=1, section_title="Intro")
    parser.parse.return_value = [parsed_section]

    chunk = MagicMock(content="Valid markdown content for knowledge base.", page_number=1, section_title="Intro")
    chunker.chunk.return_value = [chunk]

    embedder.embed_many.return_value = [[0.1] * 384]

    result = service.ingest(
        file_path,
        name="custom_name.md",
        mime_type="text/markdown",
        metadata={"scope": "engineering", "authority": "current_spec"},
    )

    assert result.status == "READY"
    assert result.name == "custom_name.md"
    assert result.metadata["scope"] == "engineering"

    # Verify storage put
    obj_storage.put.assert_called_once()
    assert obj_storage.put.call_args.kwargs["content_type"] == "text/markdown"

    # Verify chunk save
    chunk_repo.save_many.assert_called_once()
    saved_chunks = chunk_repo.save_many.call_args.args[0]
    assert len(saved_chunks) == 1
    assert saved_chunks[0].content == "Valid markdown content for knowledge base."

    # Verify vector upsert
    vec_repo.upsert_many.assert_called_once()


def test_ingest_idempotent_duplicate_returns_existing(tmp_path: Path):
    service, doc_repo, chunk_repo, vec_repo, obj_storage, parser, chunker, embedder = _setup_service()

    file_path = tmp_path / "handbook.md"
    file_path.write_text("Organization handbook.", encoding="utf-8")

    now = datetime.now(timezone.utc)
    existing_doc = KnowledgeBaseDocument(
        id="existing-123",
        name="handbook.md",
        mime_type="text/markdown",
        object_key="documents/existing-123/handbook.md",
        checksum="dummy_checksum",
        status="READY",
        created_at=now,
        updated_at=now,
        metadata={"scope": "organization"},
    )

    doc_repo.find_by_checksum.return_value = existing_doc

    result = service.ingest(
        file_path,
        mime_type="text/markdown",
        metadata={"scope": "organization"},
    )

    assert result == existing_doc
    # Crucial: no parsing, chunking, or re-upload occurred!
    parser.parse.assert_not_called()
    chunker.chunk.assert_not_called()
    obj_storage.put.assert_not_called()
    vec_repo.upsert_many.assert_not_called()


def test_ingest_replaces_existing_when_metadata_changed(tmp_path: Path):
    service, doc_repo, chunk_repo, vec_repo, obj_storage, parser, chunker, embedder = _setup_service()

    file_path = tmp_path / "handbook.md"
    file_path.write_text("Organization handbook.", encoding="utf-8")

    now = datetime.now(timezone.utc)
    existing_doc = KnowledgeBaseDocument(
        id="old-doc-123",
        name="handbook.md",
        mime_type="text/markdown",
        object_key="documents/old-doc-123/handbook.md",
        checksum="dummy_checksum",
        status="READY",
        created_at=now,
        updated_at=now,
        metadata={"scope": "old_scope"},
    )

    doc_repo.find_by_checksum.return_value = existing_doc

    parsed_section = MagicMock(content="Organization handbook.", page_number=None, section_title=None)
    parser.parse.return_value = [parsed_section]
    chunker.chunk.return_value = [parsed_section]
    embedder.embed_many.return_value = [[0.05] * 384]

    result = service.ingest(
        file_path,
        mime_type="text/markdown",
        metadata={"scope": "new_updated_scope"},
    )

    # Old resources must have been deleted
    vec_repo.delete_by_document.assert_called_with("old-doc-123")
    chunk_repo.delete_by_document.assert_called_with("old-doc-123")
    obj_storage.delete.assert_called_with("documents/old-doc-123/handbook.md")
    doc_repo.delete.assert_called_with("old-doc-123")

    # New doc is ready
    assert result.status == "READY"
    assert result.metadata["scope"] == "new_updated_scope"


def test_ingest_failure_triggers_full_rollback(tmp_path: Path):
    service, doc_repo, chunk_repo, vec_repo, obj_storage, parser, chunker, embedder = _setup_service()

    file_path = tmp_path / "faulty.md"
    file_path.write_text("Some valid content.", encoding="utf-8")

    doc_repo.find_by_checksum.return_value = None
    parser.parse.return_value = [MagicMock(content="content", page_number=1, section_title=None)]
    chunker.chunk.return_value = [MagicMock(content="content", page_number=1, section_title=None)]
    embedder.embed_many.return_value = [[0.1] * 384]

    # Vector repo fails on upsert
    vec_repo.upsert_many.side_effect = ConnectionError("Qdrant unavailable")

    with pytest.raises(ConnectionError, match="Qdrant unavailable"):
        service.ingest(file_path, mime_type="text/markdown")

    # Check cleanup actions
    vec_repo.delete_by_document.assert_called_once()
    chunk_repo.delete_by_document.assert_called_once()
    obj_storage.delete.assert_called_once()

    # Document status set to FAILED
    saved_doc = doc_repo.save.call_args.args[0]
    assert saved_doc.status == "FAILED"
