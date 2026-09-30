"""create reminders table

Revision ID: 8d4e6f7a9b21
Revises: 527f07685d62
Create Date: 2026-09-29 18:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d4e6f7a9b21"
down_revision: Union[str, Sequence[str], None] = "527f07685d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "target_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "creator_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "task",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "source_message_ts",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "source_thread_ts",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "next_reminder_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
    )

    op.create_index(
        "ix_reminders_target_user_id",
        "reminders",
        ["target_user_id"],
    )

    op.create_index(
        "ix_reminders_creator_user_id",
        "reminders",
        ["creator_user_id"],
    )

    op.create_index(
        "ix_reminders_active",
        "reminders",
        ["active"],
    )

    op.create_index(
        "ix_reminders_next_reminder_at",
        "reminders",
        ["next_reminder_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reminders_next_reminder_at",
        table_name="reminders",
    )

    op.drop_index(
        "ix_reminders_active",
        table_name="reminders",
    )

    op.drop_index(
        "ix_reminders_creator_user_id",
        table_name="reminders",
    )

    op.drop_index(
        "ix_reminders_target_user_id",
        table_name="reminders",
    )

    op.drop_table("reminders")
