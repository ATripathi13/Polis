"""create activity events table

Revision ID: ac6e86de9f1d
Revises: 9d88f747c215
Create Date: 2026-09-14

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ac6e86de9f1d"
down_revision: Union[str, Sequence[str], None] = "9d88f747c215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=255), nullable=False),
        sa.Column("person_name", sa.String(length=255), nullable=False),
        sa.Column("activity_type", sa.String(length=50), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "source_event_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "break_type",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "note",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_activity_events_person_id",
        "activity_events",
        ["person_id"],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_activity_type",
        "activity_events",
        ["activity_type"],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_occurred_at",
        "activity_events",
        ["occurred_at"],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_source_event_id",
        "activity_events",
        ["source_event_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_activity_events_source_event_id",
        table_name="activity_events",
    )
    op.drop_index(
        "ix_activity_events_occurred_at",
        table_name="activity_events",
    )
    op.drop_index(
        "ix_activity_events_activity_type",
        table_name="activity_events",
    )
    op.drop_index(
        "ix_activity_events_person_id",
        table_name="activity_events",
    )
    op.drop_table("activity_events")
