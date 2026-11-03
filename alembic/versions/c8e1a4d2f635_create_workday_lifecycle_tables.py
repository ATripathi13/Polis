"""create workday lifecycle tables

Revision ID: c8e1a4d2f635
Revises: b4f8c92e1a35
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c8e1a4d2f635"
down_revision: Union[str, Sequence[str], None] = "b4f8c92e1a35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create table workday_sessions
    op.create_table(
        "workday_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=255), nullable=False),
        sa.Column("person_name", sa.String(length=255), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("briefing_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_work_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_break_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("start_source_event_id", sa.String(length=255), nullable=True),
        sa.Column("end_source_event_id", sa.String(length=255), nullable=True),
        sa.Column("business_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Column-level indexes on workday_sessions
    op.create_index("ix_workday_sessions_person_id", "workday_sessions", ["person_id"], unique=False)
    op.create_index("ix_workday_sessions_work_date", "workday_sessions", ["work_date"], unique=False)
    op.create_index("ix_workday_sessions_status", "workday_sessions", ["status"], unique=False)
    op.create_index("ix_workday_sessions_start_source_event_id", "workday_sessions", ["start_source_event_id"], unique=False)
    op.create_index("ix_workday_sessions_end_source_event_id", "workday_sessions", ["end_source_event_id"], unique=False)

    # Table-level composite indexes on workday_sessions
    op.create_index("ix_workday_sessions_person_work_date", "workday_sessions", ["person_id", "work_date"], unique=False)
    op.create_index(
        "ix_workday_sessions_person_started_at",
        "workday_sessions",
        ["person_id", sa.text("started_at DESC")],
        unique=False,
    )

    # Partial unique index for active sessions per person
    op.create_index(
        "uq_workday_sessions_active_person",
        "workday_sessions",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # 2. Create table person_preferences
    op.create_table(
        "person_preferences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=255), nullable=False),
        sa.Column("reminders_after_signoff", sa.String(length=50), nullable=False, server_default="continue"),
        sa.Column("preferred_timezone", sa.String(length=100), nullable=True),
        sa.Column("business_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", name="uq_person_preferences_person_id"),
    )

    # Column-level index on person_id for person_preferences
    op.create_index("ix_person_preferences_person_id", "person_preferences", ["person_id"], unique=False)


def downgrade() -> None:
    # Drop person_preferences indexes and table
    op.drop_index("ix_person_preferences_person_id", table_name="person_preferences")
    op.drop_table("person_preferences")

    # Drop workday_sessions indexes and table in safe reverse order
    op.drop_index("uq_workday_sessions_active_person", table_name="workday_sessions")
    op.drop_index("ix_workday_sessions_person_started_at", table_name="workday_sessions")
    op.drop_index("ix_workday_sessions_person_work_date", table_name="workday_sessions")
    op.drop_index("ix_workday_sessions_end_source_event_id", table_name="workday_sessions")
    op.drop_index("ix_workday_sessions_start_source_event_id", table_name="workday_sessions")
    op.drop_index("ix_workday_sessions_status", table_name="workday_sessions")
    op.drop_index("ix_workday_sessions_work_date", table_name="workday_sessions")
    op.drop_index("ix_workday_sessions_person_id", table_name="workday_sessions")
    op.drop_table("workday_sessions")
