"""add tree ai analysis columns

Revision ID: 20260331_0002
Revises: 20260308_0001
Create Date: 2026-03-31 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260331_0002"
down_revision: str | None = "20260308_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trees", sa.Column("ai_status", sa.String(length=32), nullable=False, server_default="queued"))
    op.add_column("trees", sa.Column("ai_model_version", sa.String(length=120), nullable=True))
    op.add_column("trees", sa.Column("ai_summary_json", sa.Text(), nullable=True))
    op.add_column("trees", sa.Column("ai_analyzed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_trees_ai_status", "trees", ["ai_status"], unique=False)
    op.alter_column("trees", "ai_status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_trees_ai_status", table_name="trees")
    op.drop_column("trees", "ai_analyzed_at")
    op.drop_column("trees", "ai_summary_json")
    op.drop_column("trees", "ai_model_version")
    op.drop_column("trees", "ai_status")
