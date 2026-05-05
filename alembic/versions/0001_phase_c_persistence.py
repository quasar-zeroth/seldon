"""phase c persistence core

Revision ID: 0001_phase_c
Revises:
Create Date: 2026-05-05
"""
from __future__ import annotations

from alembic import op

from seldon.data.models import Base

revision = "0001_phase_c"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
