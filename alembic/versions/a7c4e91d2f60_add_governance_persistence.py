"""add governance persistence tables

Revision ID: a7c4e91d2f60
Revises: 41d06d098b31
Create Date: 2026-10-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7c4e91d2f60"
down_revision: Union[str, Sequence[str], None] = "41d06d098b31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "governance_policies",
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("enforcement_mode", sa.String(length=50), nullable=False),
        sa.Column("authority", sa.String(length=255), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("rule_description", sa.Text(), nullable=False),
        sa.Column("condition_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("policy_id"),
    )
    op.create_index("ix_governance_policies_scope", "governance_policies", ["scope"])

    op.create_table(
        "governance_approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("target_object", sa.Text(), nullable=False),
        sa.Column("requester_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("policy_id", sa.String(length=100), nullable=True),
        sa.Column("approver_id", sa.String(length=255), nullable=True),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=1000), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("status", "policy_id", "source_event_id", "source_type", "correlation_id"):
        op.create_index(
            f"ix_governance_approval_requests_{column}",
            "governance_approval_requests",
            [column],
        )

    op.create_table(
        "governance_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("policy_name", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("compliance_status", sa.String(length=50), nullable=False),
        sa.Column("affected_object", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=1000), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("authority", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("remediation_required", sa.Boolean(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "policy_id", "severity", "status", "compliance_status",
        "source_event_id", "source_type", "correlation_id",
    ):
        op.create_index(
            f"ix_governance_findings_{column}",
            "governance_findings",
            [column],
        )


def downgrade() -> None:
    for column in (
        "policy_id", "severity", "status", "compliance_status",
        "source_event_id", "source_type", "correlation_id",
    ):
        op.drop_index(
            f"ix_governance_findings_{column}",
            table_name="governance_findings",
        )
    op.drop_table("governance_findings")

    for column in ("status", "policy_id", "source_event_id", "source_type", "correlation_id"):
        op.drop_index(
            f"ix_governance_approval_requests_{column}",
            table_name="governance_approval_requests",
        )
    op.drop_table("governance_approval_requests")

    op.drop_index("ix_governance_policies_scope", table_name="governance_policies")
    op.drop_table("governance_policies")
