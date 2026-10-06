from pathlib import Path
from unittest.mock import MagicMock

from application.knowledge_base.knowledge_base_ingestion_service import (
    KnowledgeBaseIngestionService,
)


def test_ingest_automatically_classifies_known_source(tmp_path: Path):
    document_path = tmp_path / "03_maturity_code_AI_Strategy_Governance_Merged.md"
    document_path.write_text("test knowledge content", encoding="utf-8")

    document_repository = MagicMock()
    document_repository.find_by_checksum.return_value = None

    parser = MagicMock()
    parser.parse.return_value = [
        MagicMock(
            content="test knowledge content",
            page_number=None,
            section_title=None,
        )
    ]

    chunker = MagicMock()
    chunker.chunk.return_value = parser.parse.return_value

    embedding_client = MagicMock()
    embedding_client.embed_many.return_value = [[0.1, 0.2, 0.3]]

    service = KnowledgeBaseIngestionService(
        document_repository=document_repository,
        chunk_repository=MagicMock(),
        vector_repository=MagicMock(),
        object_storage=MagicMock(),
        parser=parser,
        chunker=chunker,
        embedding_client=embedding_client,
    )

    service.ingest(
        document_path,
        mime_type="text/markdown",
    )

    saved_document = document_repository.save.call_args.args[0]

    assert saved_document.metadata == {
        "knowledge_type": "framework",
        "scope": "organization",
        "authority": "current_framework",
        "source_type": "internal",
    }
