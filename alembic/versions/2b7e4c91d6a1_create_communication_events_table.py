"""create communication events table

Revision ID: 2b7e4c91d6a1
Revises: f73cc5aa4036
Create Date: 2026-09-15 11:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2b7e4c91d6a1"
down_revision: Union[str, Sequence[str], None] = "f73cc5aa4036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "communication_events",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "correlation_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "source_event_id",
            sa.String(length=1000),
            nullable=False,
        ),
        sa.Column(
            "actor",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "channel",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "content",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "attachments",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "references",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "mentions",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "source_event_id",
            name="uq_communication_source_event",
        ),
    )

    op.create_index(
        "ix_communication_events_correlation_id",
        "communication_events",
        ["correlation_id"],
    )

    op.create_index(
        "ix_communication_events_source",
        "communication_events",
        ["source"],
    )

    op.create_index(
        "ix_communication_events_source_event_id",
        "communication_events",
        ["source_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_communication_events_source_event_id",
        table_name="communication_events",
    )

    op.drop_index(
        "ix_communication_events_source",
        table_name="communication_events",
    )

    op.drop_index(
        "ix_communication_events_correlation_id",
        table_name="communication_events",
    )

    op.drop_table("communication_events")
