"""Persistent reusable entity tags; reports use existing durable AgentRun rows."""
import sqlalchemy as sa
from alembic import op

revision = "0005_entity_tags"
down_revision = "0004_scenario_original_prompt"
branch_labels = None
depends_on = None


def upgrade():
    if "tags" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("erg_nodes")}:
        op.add_column("erg_nodes", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("erg_nodes", "tags")
