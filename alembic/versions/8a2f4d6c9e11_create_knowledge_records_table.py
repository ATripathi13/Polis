"""create knowledge records table

Revision ID: 8a2f4d6c9e11
Revises: 7c1a2f4e8b91
Create Date: 2026-09-21 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8a2f4d6c9e11"
down_revision: Union[str, Sequence[str], None] = "7c1a2f4e8b91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_records",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "subject",
            sa.String(length=1000),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "canonical_text",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "embedding",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject",
            name="uq_knowledge_records_subject",
        ),
    )

    op.create_index(
        "ix_knowledge_records_subject",
        "knowledge_records",
        ["subject"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_records_subject",
        table_name="knowledge_records",
    )

    op.drop_table("knowledge_records")