"""pgvector embedding storage

Revision ID: 0002_pgvector_embeddings
Revises: 0001_phase_c
Create Date: 2026-05-09
"""
from __future__ import annotations

from alembic import op

revision = "0002_pgvector_embeddings"
down_revision = "0001_phase_c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS content_embedding_vector vector(1536)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_entries_embedding_vector "
        "ON kb_entries USING ivfflat (content_embedding_vector vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_kb_entries_embedding_vector")
    op.execute("ALTER TABLE kb_entries DROP COLUMN IF EXISTS content_embedding_vector")
