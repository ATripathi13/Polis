"""create meeting transcripts table

Revision ID: 29f700c54e8f
Revises: c5d518b4d723
Create Date: 2026-09-10 13:44:27.220592

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "29f700c54e8f"
down_revision: Union[str, Sequence[str], None] = "c5d518b4d723"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meeting_transcripts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "participants",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_meeting_transcripts_meeting_id",
        "meeting_transcripts",
        ["meeting_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meeting_transcripts_meeting_id",
        table_name="meeting_transcripts",
    )

    op.drop_table("meeting_transcripts")
