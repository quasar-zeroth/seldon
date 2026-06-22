"""store original scenario prompt

Revision ID: 0004_scenario_original_prompt
Revises: 0003_durable_ops_jobs
Create Date: 2026-05-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004_scenario_original_prompt"
down_revision = "0003_durable_ops_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("scenarios")}
    if "original_prompt" not in columns:
        op.add_column("scenarios", sa.Column("original_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("scenarios")}
    if "original_prompt" in columns:
        op.drop_column("scenarios", "original_prompt")
