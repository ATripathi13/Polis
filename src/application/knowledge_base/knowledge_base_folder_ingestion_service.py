from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .knowledge_base_ingestion_service import (
    KnowledgeBaseIngestionService,
)


@dataclass(frozen=True, slots=True)
class KnowledgeBaseFolderIngestionResult:
    """
    Result of scanning and ingesting a Knowledge Base folder.
    """

    ingested: list[str]
    skipped: list[str]
    failed: dict[str, str]


class KnowledgeBaseFolderIngestionService:
    """
    Scans a folder and ingests all supported Knowledge Base files.
    """

    MIME_TYPES = {
        ".pdf": "application/pdf",
        ".docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        ".txt": "text/plain",
        ".md": "text/markdown",
    }

    def __init__(
        self,
        *,
        ingestion_service: KnowledgeBaseIngestionService,
    ) -> None:
        self._ingestion_service = ingestion_service

    def ingest_folder(
        self,
        folder: Path,
    ) -> KnowledgeBaseFolderIngestionResult:
        """
        Scan the supplied folder recursively and ingest all
        supported files.
        """

        if not folder.exists():
            raise FileNotFoundError(folder)

        if not folder.is_dir():
            raise NotADirectoryError(folder)

        ingested: list[str] = []
        skipped: list[str] = []
        failed: dict[str, str] = {}

        for path in sorted(
            folder.rglob("*"),
        ):
            if not path.is_file():
                continue

            mime_type = self.MIME_TYPES.get(
                path.suffix.lower()
            )

            if mime_type is None:
                skipped.append(
                    str(path)
                )
                continue

            try:
                document = self._ingestion_service.ingest(
                    path,
                    mime_type=mime_type,
                )

                if document.status == "READY":
                    ingested.append(
                        str(path)
                    )
                else:
                    failed[str(path)] = (
                        f"Unexpected document status: "
                        f"{document.status}"
                    )

            except Exception as exc:
                failed[str(path)] = str(exc)

        return KnowledgeBaseFolderIngestionResult(
            ingested=ingested,
            skipped=skipped,
            failed=failed,
        )