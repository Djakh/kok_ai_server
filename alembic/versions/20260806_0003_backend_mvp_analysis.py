"""add provider-backed tree analyses and scan history

Revision ID: 20260806_0003
Revises: 20260331_0002
Create Date: 2026-08-06 13:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260806_0003"
down_revision: str | None = "20260331_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trees", sa.Column("confirmed_species", sa.String(length=255), nullable=True))
    op.add_column("trees", sa.Column("candidate_species", sa.String(length=255), nullable=True))
    op.add_column("trees", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("trees", sa.Column("latest_health_status", sa.String(length=40), nullable=True))

    op.create_table(
        "tree_analyses",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("normalized_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_provider_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_tree_analyses_owner_idempotency"
        ),
    )
    op.create_index(
        "ix_tree_analyses_owner_created", "tree_analyses", ["owner_user_id", "created_at"]
    )
    op.create_index("ix_tree_analyses_status", "tree_analyses", ["status"])

    op.create_table(
        "tree_analysis_images",
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organ", sa.String(length=16), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["tree_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tree_analysis_images_analysis", "tree_analysis_images", ["analysis_id"]
    )

    op.create_table(
        "tree_scans",
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("health_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["tree_analyses.id"]),
        sa.ForeignKeyConstraint(["tree_id"], ["trees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", name="uq_tree_scans_analysis_id"),
    )
    op.create_index(
        "ix_tree_scans_tree_analyzed", "tree_scans", ["tree_id", "analyzed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_tree_scans_tree_analyzed", table_name="tree_scans")
    op.drop_table("tree_scans")
    op.drop_index("ix_tree_analysis_images_analysis", table_name="tree_analysis_images")
    op.drop_table("tree_analysis_images")
    op.drop_index("ix_tree_analyses_status", table_name="tree_analyses")
    op.drop_index("ix_tree_analyses_owner_created", table_name="tree_analyses")
    op.drop_table("tree_analyses")
    op.drop_column("trees", "latest_health_status")
    op.drop_column("trees", "notes")
    op.drop_column("trees", "candidate_species")
    op.drop_column("trees", "confirmed_species")
