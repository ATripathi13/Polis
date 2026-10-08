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

class KnowledgeBaseDocumentModel(Base):
    __tablename__ = "knowledge_base_documents"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    mime_type: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    object_key: Mapped[str] = mapped_column(
        String(1000),
        unique=True,
        index=True,
        nullable=False,
    )

    checksum: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )


class KnowledgeBaseChunkModel(Base):
    __tablename__ = "knowledge_base_chunks"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    document_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    page_number: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    section_title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    qdrant_point_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
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

class CommunicationEventModel(Base):
    __tablename__ = "communication_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    correlation_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    correlation_business_id: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        default="",
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    source_event_id: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        index=True,
    )

    actor: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    channel: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    content: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    attachments: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    references: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    mentions: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
class ConversationMemoryModel(Base):
    __tablename__ = "conversation_memory"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    channel_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    thread_ts: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    history: Mapped[list] = mapped_column(
        JSONB,
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
class ReminderModel(Base):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    target_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    creator_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    task: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    channel_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    source_message_ts: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    source_thread_ts: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    active: Mapped[bool] = mapped_column(
        nullable=False,
        index=True,
    )

    next_reminder_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

class OperationalItemModel(Base):
    __tablename__ = "operational_items"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    item_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    priority: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    owner_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    owner_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    source_event_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    evidence: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
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
