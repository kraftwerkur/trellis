"""Add API keys and cost events tables for LLM Gateway.

Revision ID: b2c3d4e5f6a7
Revises: a7f7fe700d8c
Create Date: 2026-02-22 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a7f7fe700d8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key_hash", sa.String(), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.agent_id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("budget_daily_usd", sa.Float(), nullable=True),
        sa.Column("budget_monthly_usd", sa.Float(), nullable=True),
        sa.Column("preferred_provider", sa.String(), nullable=True),
        sa.Column("default_model", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "cost_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=False, index=True),
        sa.Column("model_requested", sa.String(), nullable=False),
        sa.Column("model_used", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("has_tool_calls", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_table("cost_events")
    op.drop_table("api_keys")
