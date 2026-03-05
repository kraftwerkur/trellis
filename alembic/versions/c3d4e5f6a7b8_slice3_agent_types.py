"""Slice 3: Add agent_type, llm_config, function_ref to agents table.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("agent_type", sa.String(), server_default="http", nullable=False))
    op.add_column("agents", sa.Column("llm_config", sa.JSON(), nullable=True))
    op.add_column("agents", sa.Column("function_ref", sa.String(), nullable=True))
    # Make endpoint nullable (function/llm agents don't need one)
    with op.batch_alter_table("agents") as batch_op:
        batch_op.alter_column("endpoint", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.drop_column("agents", "function_ref")
    op.drop_column("agents", "llm_config")
    op.drop_column("agents", "agent_type")
    with op.batch_alter_table("agents") as batch_op:
        batch_op.alter_column("endpoint", existing_type=sa.String(), nullable=False)
