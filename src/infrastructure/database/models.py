from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .connection import Base


class KnowledgeRecordModel(Base):
    __tablename__ = "knowledge_records"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    subject: Mapped[str] = mapped_column(
        String(1000),
        unique=True,
        index=True,
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    canonical_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    tags: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    embedding: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )