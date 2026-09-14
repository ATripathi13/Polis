"""allow long Teams meeting ids

Revision ID: ab24fbb8ddf3
Revises: 29f700c54e8f
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ab24fbb8ddf3"
down_revision: Union[str, Sequence[str], None] = "29f700c54e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "meeting_transcripts",
        "meeting_id",
        existing_type=sa.String(length=36),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "meeting_transcripts",
        "meeting_id",
        existing_type=sa.Text(),
        type_=sa.String(length=36),
        existing_nullable=False,
    )