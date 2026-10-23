"""
Unit tests for KnowledgeBaseFolderIngestionService.
"""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from application.knowledge_base.knowledge_base_folder_ingestion_service import (
    KnowledgeBaseFolderIngestionService,
)
from domain.knowledge_base import KnowledgeBaseDocument


def test_folder_not_found_raises(tmp_path: Path):
    ingestion_service = MagicMock()
    service = KnowledgeBaseFolderIngestionService(ingestion_service=ingestion_service)

    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        service.ingest_folder(non_existent)


def test_file_path_not_directory_raises(tmp_path: Path):
    file_path = tmp_path / "regular_file.txt"
    file_path.write_text("Hello", encoding="utf-8")

    ingestion_service = MagicMock()
    service = KnowledgeBaseFolderIngestionService(ingestion_service=ingestion_service)

    with pytest.raises(NotADirectoryError):
        service.ingest_folder(file_path)


def test_ingest_folder_processes_supported_and_skips_unsupported(tmp_path: Path):
    # Supported files
    doc_md = tmp_path / "guide.md"
    doc_md.write_text("# Guide", encoding="utf-8")

    doc_txt = tmp_path / "notes.txt"
    doc_txt.write_text("Notes", encoding="utf-8")

    # Subdirectory with supported file
    sub = tmp_path / "subfolder"
    sub.mkdir()
    doc_sub = sub / "sub_doc.pdf"
    doc_sub.write_bytes(b"%PDF-1.4 dummy")

    # Unsupported files
    unsupported_json = tmp_path / "data.json"
    unsupported_json.write_text("{}", encoding="utf-8")

    unsupported_csv = tmp_path / "table.csv"
    unsupported_csv.write_text("a,b", encoding="utf-8")

    ingestion_service = MagicMock()

    def mock_ingest(path, mime_type):
        if "notes.txt" in str(path):
            raise RuntimeError("Parser failure on notes")
        return MagicMock(status="READY")

    ingestion_service.ingest.side_effect = mock_ingest

    service = KnowledgeBaseFolderIngestionService(ingestion_service=ingestion_service)
    result = service.ingest_folder(tmp_path)

    # guide.md and sub_doc.pdf should succeed
    assert str(doc_md) in result.ingested
    assert str(doc_sub) in result.ingested
    assert len(result.ingested) == 2

    # data.json and table.csv should be skipped
    assert str(unsupported_json) in result.skipped
    assert str(unsupported_csv) in result.skipped
    assert len(result.skipped) == 2

    # notes.txt raised an error, so it should be in failed
    assert str(doc_txt) in result.failed
    assert "Parser failure on notes" in result.failed[str(doc_txt)]


def test_ingest_folder_unexpected_status(tmp_path: Path):
    doc_md = tmp_path / "draft.md"
    doc_md.write_text("# Draft", encoding="utf-8")

    ingestion_service = MagicMock()
    ingestion_service.ingest.return_value = MagicMock(status="FAILED")

    service = KnowledgeBaseFolderIngestionService(ingestion_service=ingestion_service)
    result = service.ingest_folder(tmp_path)

    assert len(result.ingested) == 0
    assert str(doc_md) in result.failed
    assert "Unexpected document status: FAILED" in result.failed[str(doc_md)]
