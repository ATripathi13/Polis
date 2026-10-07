"""add communication correlation business id

Revision ID: e1f29d90ebac
Revises: 8d4e6f7a9b21
Create Date: 2026-10-07 12:32:36.534577

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f29d90ebac'
down_revision: Union[str, Sequence[str], None] = '8d4e6f7a9b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "communication_events",
        sa.Column(
            "correlation_business_id",
            sa.String(length=1000),
            nullable=False,
            server_default="",
        ),
    )

    op.alter_column(
        "communication_events",
        "correlation_business_id",
        server_default=None,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(
        "communication_events",
        "correlation_business_id",
    )
