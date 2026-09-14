"""create teams subscriptions table

Revision ID: f73cc5aa4036
Revises: ab24fbb8ddf3
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f73cc5aa4036"
down_revision: Union[str, Sequence[str], None] = "ab24fbb8ddf3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teams_subscriptions",
        sa.Column(
            "id",
            sa.String(length=36),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "resource",
            sa.String(length=2000),
            nullable=False,
        ),
        sa.Column(
            "expiration_datetime",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "client_state",
            sa.String(length=255),
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
    )

    op.create_index(
        "ix_teams_subscriptions_subscription_id",
        "teams_subscriptions",
        ["subscription_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_teams_subscriptions_subscription_id",
        table_name="teams_subscriptions",
    )
    op.drop_table("teams_subscriptions")