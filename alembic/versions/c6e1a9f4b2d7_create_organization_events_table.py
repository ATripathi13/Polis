"""create organization events table

Revision ID: c6e1a9f4b2d7
Revises: b02ff94dcd19
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c6e1a9f4b2d7"
down_revision: Union[str, Sequence[str], None] = "b02ff94dcd19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_events",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "observations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "source_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "source_event_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_event_id",
            "event_type",
            name="uq_organization_events_source_event_type",
        ),
    )

    op.create_index(
        "ix_organization_events_event_type",
        "organization_events",
        ["event_type"],
    )
    op.create_index(
        "ix_organization_events_source_type",
        "organization_events",
        ["source_type"],
    )
    op.create_index(
        "ix_organization_events_source_event_id",
        "organization_events",
        ["source_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_events_source_event_id",
        table_name="organization_events",
    )
    op.drop_index(
        "ix_organization_events_source_type",
        table_name="organization_events",
    )
    op.drop_index(
        "ix_organization_events_event_type",
        table_name="organization_events",
    )
    op.drop_table("organization_events")
