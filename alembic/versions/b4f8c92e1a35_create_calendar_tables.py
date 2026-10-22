"""create calendar tables

Revision ID: b4f8c92e1a35
Revises: a7c4e91d2f60
Create Date: 2026-10-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b4f8c92e1a35"
down_revision: Union[str, Sequence[str], None] = "a7c4e91d2f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("entry_type", sa.String(length=50), nullable=False),
        sa.Column("creator_id", sa.String(length=255), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("audience_type", sa.String(length=50), nullable=False),
        sa.Column("audience_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in (
        "entry_type",
        "creator_id",
        "start_time",
        "audience_type",
        "audience_id",
        "status",
    ):
        op.create_index(f"ix_calendar_entries_{col}", "calendar_entries", [col])

    op.create_table(
        "calendar_reminder_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_id", sa.String(length=255), nullable=False),
        sa.Column("delivery_channel", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["calendar_entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_calendar_reminder_deliveries_idempotency_key",
        ),
    )
    for col in ("entry_id", "recipient_id", "due_at", "status", "idempotency_key"):
        op.create_index(
            f"ix_calendar_reminder_deliveries_{col}",
            "calendar_reminder_deliveries",
            [col],
        )


def downgrade() -> None:
    for col in ("idempotency_key", "status", "due_at", "recipient_id", "entry_id"):
        op.drop_index(
            f"ix_calendar_reminder_deliveries_{col}",
            table_name="calendar_reminder_deliveries",
        )
    op.drop_table("calendar_reminder_deliveries")

    for col in (
        "status",
        "audience_id",
        "audience_type",
        "start_time",
        "creator_id",
        "entry_type",
    ):
        op.drop_index(f"ix_calendar_entries_{col}", table_name="calendar_entries")
    op.drop_table("calendar_entries")
