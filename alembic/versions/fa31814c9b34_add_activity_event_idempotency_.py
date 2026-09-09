"""add activity event idempotency constraint

Revision ID: fa31814c9b34
Revises: 9d88f747c215
Create Date: 2026-09-07 11:54:03.892647

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "fa31814c9b34"
down_revision: Union[str, Sequence[str], None] = "9d88f747c215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add idempotency constraint for Slack activity events."""
    op.create_unique_constraint(
        "uq_activity_events_person_source_event",
        "activity_events",
        ["person_id", "source_event_id"],
    )


def downgrade() -> None:
    """Remove idempotency constraint."""
    op.drop_constraint(
        "uq_activity_events_person_source_event",
        "activity_events",
        type_="unique",
    )