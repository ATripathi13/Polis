from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """
    A retrieval-sized piece of a parsed document.
    """

    content: str
    page_number: int | None = None
    section_title: str | None = None


class DocumentChunker:
    """
    Splits parsed document sections into overlapping chunks.
    """

    def __init__(
        self,
        *,
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError(
                "chunk_size must be greater than zero."
            )

        if chunk_overlap < 0:
            raise ValueError(
                "chunk_overlap cannot be negative."
            )

        if chunk_overlap >= chunk_size:
            raise ValueError(
                "chunk_overlap must be smaller than chunk_size."
            )

        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(
        self,
        sections,
    ) -> list[DocumentChunk]:
        """
        Chunk parsed document sections while preserving
        page and section metadata.
        """

        chunks: list[DocumentChunk] = []

        for section in sections:
            text = " ".join(
                section.content.split()
            ).strip()

            if not text:
                continue

            for content in self._split(text):
                chunks.append(
                    DocumentChunk(
                        content=content,
                        page_number=section.page_number,
                        section_title=section.section_title,
                    )
                )

        return chunks

    def _split(
        self,
        text: str,
    ) -> list[str]:
        if len(text) <= self._chunk_size:
            return [text]

        chunks: list[str] = []

        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(
                start + self._chunk_size,
                text_length,
            )

            if end < text_length:
                boundary = text.rfind(
                    " ",
                    start,
                    end,
                )

                if boundary > start:
                    end = boundary

            chunk = text[start:end].strip()

            if chunk:
                chunks.append(chunk)

            if end >= text_length:
                break

            next_start = end - self._chunk_overlap

            if next_start <= start:
                next_start = end

            start = next_start

        return chunks