"""create conversation memory table

Revision ID: 7c1a2f4e8b91
Revises: 2b7e4c91d6a1
Create Date: 2026-09-16 16:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7c1a2f4e8b91"
down_revision: Union[str, Sequence[str], None] = "2b7e4c91d6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_memory",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "thread_ts",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "history",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "thread_ts",
            name="uq_conversation_memory_channel_thread",
        ),
    )

    op.create_index(
        "ix_conversation_memory_channel_id",
        "conversation_memory",
        ["channel_id"],
    )

    op.create_index(
        "ix_conversation_memory_thread_ts",
        "conversation_memory",
        ["thread_ts"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_memory_thread_ts",
        table_name="conversation_memory",
    )

    op.drop_index(
        "ix_conversation_memory_channel_id",
        table_name="conversation_memory",
    )

    op.drop_table("conversation_memory")