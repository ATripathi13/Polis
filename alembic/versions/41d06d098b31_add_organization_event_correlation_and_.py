"""add organization event correlation and occurrence

Revision ID: 41d06d098b31
Revises: c6e1a9f4b2d7
Create Date: 2026-10-13 10:22:09.215428
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "41d06d098b31"
down_revision: Union[str, Sequence[str], None] = "c6e1a9f4b2d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organization_events",
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "organization_events",
        sa.Column(
            "correlation_business_id",
            sa.String(length=1000),
            nullable=True,
        ),
    )
    op.add_column(
        "organization_events",
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_organization_events_correlation_id",
        "organization_events",
        ["correlation_id"],
    )
    op.create_index(
        "ix_organization_events_correlation_business_id",
        "organization_events",
        ["correlation_business_id"],
    )
    op.create_index(
        "ix_organization_events_occurred_at",
        "organization_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_events_occurred_at",
        table_name="organization_events",
    )
    op.drop_index(
        "ix_organization_events_correlation_business_id",
        table_name="organization_events",
    )
    op.drop_index(
        "ix_organization_events_correlation_id",
        table_name="organization_events",
    )

    op.drop_column("organization_events", "occurred_at")
    op.drop_column("organization_events", "correlation_business_id")
    op.drop_column("organization_events", "correlation_id")
