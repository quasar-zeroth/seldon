"""durable ops jobs

Revision ID: 0003_durable_ops_jobs
Revises: 0002_pgvector_embeddings
Create Date: 2026-05-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_durable_ops_jobs"
down_revision = "0002_pgvector_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "ops_jobs" in inspect(bind).get_table_names():
        return
    op.create_table(
        "ops_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True, unique=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ops_jobs_status", "ops_jobs", ["status"])
    op.create_index("ix_ops_jobs_kind_status", "ops_jobs", ["kind", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    if "ops_jobs" not in inspect(bind).get_table_names():
        return
    op.drop_index("ix_ops_jobs_kind_status", table_name="ops_jobs")
    op.drop_index("ix_ops_jobs_status", table_name="ops_jobs")
    op.drop_table("ops_jobs")
