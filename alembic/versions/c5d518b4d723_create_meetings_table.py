"""create meetings table

Revision ID: c5d518b4d723
Revises: fa31814c9b34
Create Date: 2026-09-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c5d518b4d723"
down_revision: Union[str, Sequence[str], None] = "fa31814c9b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_meetings_external_id",
        "meetings",
        ["external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meetings_external_id",
        table_name="meetings",
    )

    op.drop_table("meetings")
