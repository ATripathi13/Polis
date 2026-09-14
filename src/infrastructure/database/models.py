from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .connection import Base
from sqlalchemy import Text

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


class ActivityEventModel(Base):
    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    person_id: Mapped[str] = mapped_column(
        String(255),
        index=True,
        nullable=False,
    )

    person_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    activity_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    source_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    break_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

class MeetingModel(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    external_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )

class MeetingTranscriptModel(Base):
    __tablename__ = "meeting_transcripts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    transcript: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    participants: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )

class TeamsSubscriptionModel(Base):
    __tablename__ = "teams_subscriptions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    subscription_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    resource: Mapped[str] = mapped_column(
        String(2000),
        nullable=False,
    )

    expiration_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    client_state: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )