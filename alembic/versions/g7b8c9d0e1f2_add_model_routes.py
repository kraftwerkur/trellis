"""add model_routes table

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-02-24 22:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_routes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_name", sa.String(), nullable=False, unique=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("cost_per_1k_input", sa.Float(), server_default="0.0"),
        sa.Column("cost_per_1k_output", sa.Float(), server_default="0.0"),
        sa.Column("active", sa.Boolean(), server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("model_routes")
