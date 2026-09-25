from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader


@dataclass(frozen=True, slots=True)
class ParsedDocumentSection:
    """
    Extracted document content with source location metadata.
    """

    content: str
    page_number: int | None = None
    section_title: str | None = None


class DocumentParser:
    """
    Extract text from supported Knowledge Base document formats.
    """

    SUPPORTED_MIME_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    }

    def parse(
        self,
        path: Path,
        mime_type: str,
    ) -> list[ParsedDocumentSection]:
        if not path.exists():
            raise FileNotFoundError(path)

        if mime_type not in self.SUPPORTED_MIME_TYPES:
            raise ValueError(
                f"Unsupported document type: {mime_type}"
            )

        if mime_type == "application/pdf":
            return self._parse_pdf(path)

        if (
            mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            return self._parse_docx(path)

        return self._parse_text(path)

    @staticmethod
    def _parse_pdf(
        path: Path,
    ) -> list[ParsedDocumentSection]:
        reader = PdfReader(str(path))

        sections: list[ParsedDocumentSection] = []

        for page_number, page in enumerate(
            reader.pages,
            start=1,
        ):
            text = (
                page.extract_text()
                or ""
            ).strip()

            if not text:
                continue

            sections.append(
                ParsedDocumentSection(
                    content=text,
                    page_number=page_number,
                )
            )

        return sections

    @staticmethod
    def _parse_docx(
        path: Path,
    ) -> list[ParsedDocumentSection]:
        document = Document(str(path))

        sections: list[ParsedDocumentSection] = []
        current_section: str | None = None

        for paragraph in document.paragraphs:
            text = paragraph.text.strip()

            if not text:
                continue

            style_name = (
                paragraph.style.name.lower()
                if paragraph.style is not None
                else ""
            )

            if style_name.startswith("heading"):
                current_section = text
                continue

            sections.append(
                ParsedDocumentSection(
                    content=text,
                    section_title=current_section,
                )
            )

        return sections

    @staticmethod
    def _parse_text(
        path: Path,
    ) -> list[ParsedDocumentSection]:
        text = path.read_text(
            encoding="utf-8",
        ).strip()

        if not text:
            return []

        sections: list[ParsedDocumentSection] = []

        current_section: str | None = None
        current_lines: list[str] = []

        def flush_section() -> None:
            content = "\n".join(
                line.strip()
                for line in current_lines
                if line.strip()
            ).strip()

            if not content:
                return

            sections.append(
                ParsedDocumentSection(
                    content=content,
                    section_title=current_section,
                )
            )

        for line in text.splitlines():
            stripped = line.strip()

            if not stripped:
                continue

            if stripped.startswith("#"):
                flush_section()
                current_lines.clear()

                current_section = (
                    stripped.lstrip("#").strip()
                )

                continue

            if stripped == "---":
                continue

            current_lines.append(stripped)

        flush_section()

        return sections