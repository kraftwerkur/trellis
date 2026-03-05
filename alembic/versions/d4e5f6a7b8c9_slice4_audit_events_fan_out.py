"""Slice 4: audit_events table and fan_out column on rules.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create audit_events table
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("envelope_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_trace_id", "audit_events", ["trace_id"])
    op.create_index("ix_audit_events_envelope_id", "audit_events", ["envelope_id"])
    op.create_index("ix_audit_events_agent_id", "audit_events", ["agent_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])

    # Add fan_out column to rules
    with op.batch_alter_table("rules") as batch_op:
        batch_op.add_column(sa.Column("fan_out", sa.Boolean(), nullable=True, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("rules") as batch_op:
        batch_op.drop_column("fan_out")
    op.drop_table("audit_events")
