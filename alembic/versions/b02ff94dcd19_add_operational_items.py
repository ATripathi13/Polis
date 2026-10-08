"""add operational items

Revision ID: b02ff94dcd19
Revises: e1f29d90ebac
Create Date: 2026-10-07 18:06:28.297620

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b02ff94dcd19'
down_revision: Union[str, Sequence[str], None] = 'e1f29d90ebac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "operational_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=50), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("owner_name", sa.String(length=255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_operational_items_item_type",
        "operational_items",
        ["item_type"],
    )
    op.create_index(
        "ix_operational_items_status",
        "operational_items",
        ["status"],
    )
    op.create_index(
        "ix_operational_items_priority",
        "operational_items",
        ["priority"],
    )
    op.create_index(
        "ix_operational_items_owner_id",
        "operational_items",
        ["owner_id"],
    )
    op.create_index(
        "ix_operational_items_due_at",
        "operational_items",
        ["due_at"],
    )
    op.create_index(
        "ix_operational_items_source_event_id",
        "operational_items",
        ["source_event_id"],
    )
    op.create_index(
        "ix_operational_items_source_type",
        "operational_items",
        ["source_type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_operational_items_source_type",
        table_name="operational_items",
    )
    op.drop_index(
        "ix_operational_items_source_event_id",
        table_name="operational_items",
    )
    op.drop_index(
        "ix_operational_items_due_at",
        table_name="operational_items",
    )
    op.drop_index(
        "ix_operational_items_owner_id",
        table_name="operational_items",
    )
    op.drop_index(
        "ix_operational_items_priority",
        table_name="operational_items",
    )
    op.drop_index(
        "ix_operational_items_status",
        table_name="operational_items",
    )
    op.drop_index(
        "ix_operational_items_item_type",
        table_name="operational_items",
    )
    op.drop_table("operational_items")
