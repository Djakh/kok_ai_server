"""Kindwise and authoritative mobile registration contract.

Revision ID: 20260815_0005
Revises: 20260810_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260815_0005"
down_revision: str | None = "20260810_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tree_analyses", sa.Column("numeric_provider_custom_id", sa.BigInteger()))
    op.add_column("tree_analyses", sa.Column("location_evidence", postgresql.JSONB()))
    op.add_column("tree_analyses", sa.Column("provider_name", sa.String(64), server_default="kindwise_plant_id", nullable=False))
    op.add_column("tree_analyses", sa.Column("provider_is_plant_binary", sa.Boolean()))
    op.add_column("tree_analyses", sa.Column("provider_is_plant_probability", sa.Float()))
    op.add_column("tree_analyses", sa.Column("health_mode", sa.String(8), server_default="off", nullable=False))
    op.create_unique_constraint("uq_tree_analyses_provider_custom_id", "tree_analyses", ["numeric_provider_custom_id"])
    op.execute("CREATE SEQUENCE IF NOT EXISTS tree_analysis_provider_custom_id_seq")
    op.execute("UPDATE tree_analyses SET numeric_provider_custom_id = nextval('tree_analysis_provider_custom_id_seq') WHERE numeric_provider_custom_id IS NULL")
    op.alter_column("tree_analyses", "numeric_provider_custom_id", server_default=sa.text("nextval('tree_analysis_provider_custom_id_seq')"), nullable=False)
    op.add_column("tree_analysis_images", sa.Column("ordinal", sa.Integer(), server_default="0", nullable=False))
    op.add_column("tree_analysis_images", sa.Column("original_object_key", sa.String(512)))

    op.create_table(
        "tree_analysis_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tree_analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_taxon_id", sa.String(160)),
        sa.Column("scientific_name", sa.String(255), nullable=False),
        sa.Column("common_name", sa.String(255)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("genus", sa.String(255)),
        sa.Column("family", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("representative_image_url", sa.Text()),
        sa.Column("image_source_url", sa.Text()),
        sa.Column("attribution_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "ordinal", name="uq_analysis_candidate_ordinal"),
    )
    op.create_index("ix_analysis_candidates_analysis", "tree_analysis_candidates", ["analysis_id"])
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method", sa.String(12), nullable=False),
        sa.Column("route", sa.String(255), nullable=False),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", postgresql.JSONB()),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("principal_id", "method", "route", "key", name="uq_idempotency_scope"),
    )
    op.create_index("ix_idempotency_expiry", "idempotency_records", ["expires_at"])
    op.add_column("trees", sa.Column("analysis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tree_analyses.id")))
    op.add_column("trees", sa.Column("selected_candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tree_analysis_candidates.id")))
    op.add_column("trees", sa.Column("manual_scientific_name", sa.String(255)))
    op.add_column("trees", sa.Column("identification_source", sa.String(32), nullable=False, server_default="unknown"))
    op.add_column("trees", sa.Column("duplicate_check_status", sa.String(40)))
    op.create_unique_constraint("uq_trees_analysis_id", "trees", ["analysis_id"])
    for name, column in (
        ("accepted_sample_count", sa.Integer()),
        ("rejected_sample_count", sa.Integer()),
        ("capture_duration_ms", sa.Integer()),
        ("best_sample_accuracy_meters", sa.Float()),
        ("evidence_captured_at", sa.DateTime(timezone=True)),
        ("quality", sa.String(16)),
    ):
        op.add_column("tree_locations", sa.Column(name, column))
    op.add_column("refresh_tokens", sa.Column("token_family_id", postgresql.UUID(as_uuid=True)))
    op.add_column("refresh_tokens", sa.Column("rotated_at", sa.DateTime(timezone=True)))
    op.add_column("refresh_tokens", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE refresh_tokens SET token_family_id=id WHERE token_family_id IS NULL")
    op.alter_column("refresh_tokens", "token_family_id", nullable=False)
    op.create_index("uq_users_email_normalized", "users", [sa.text("lower(email)")], unique=True)
    op.create_index("uq_users_username_normalized", "users", [sa.text("lower(username)")], unique=True)
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outbox_pending", "outbox_events", ["status", "available_at"])
    op.add_column("uploaded_assets", sa.Column("original_storage_key", sa.String(512)))
    op.add_column("uploaded_assets", sa.Column("sha256", sa.String(64)))
    op.add_column("uploaded_assets", sa.Column("width", sa.Integer()))
    op.add_column("uploaded_assets", sa.Column("height", sa.Integer()))
    op.add_column("uploaded_assets", sa.Column("purpose", sa.String(32), nullable=False, server_default="general"))
    op.add_column("uploaded_assets", sa.Column("status", sa.String(24), nullable=False, server_default="available"))
    op.add_column("uploaded_assets", sa.Column("attached_at", sa.DateTime(timezone=True)))
    op.add_column("uploaded_assets", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_uploaded_assets_original_storage_key", "uploaded_assets", ["original_storage_key"])


def downgrade() -> None:
    op.drop_constraint("uq_uploaded_assets_original_storage_key", "uploaded_assets", type_="unique")
    for name in ("expires_at", "attached_at", "status", "purpose", "height", "width", "sha256", "original_storage_key"):
        op.drop_column("uploaded_assets", name)
    op.drop_table("outbox_events")
    op.drop_index("uq_users_username_normalized", table_name="users")
    op.drop_index("uq_users_email_normalized", table_name="users")
    op.drop_column("refresh_tokens", "revoked_at")
    op.drop_column("refresh_tokens", "rotated_at")
    op.drop_column("refresh_tokens", "token_family_id")
    for name in ("quality", "evidence_captured_at", "best_sample_accuracy_meters", "capture_duration_ms", "rejected_sample_count", "accepted_sample_count"):
        op.drop_column("tree_locations", name)
    op.drop_constraint("uq_trees_analysis_id", "trees", type_="unique")
    for name in ("duplicate_check_status", "identification_source", "manual_scientific_name", "selected_candidate_id", "analysis_id"):
        op.drop_column("trees", name)
    op.drop_table("idempotency_records")
    op.drop_table("tree_analysis_candidates")
    op.drop_column("tree_analysis_images", "original_object_key")
    op.drop_column("tree_analysis_images", "ordinal")
    op.drop_constraint("uq_tree_analyses_provider_custom_id", "tree_analyses", type_="unique")
    for column in ("health_mode", "provider_is_plant_probability", "provider_is_plant_binary", "provider_name", "location_evidence", "numeric_provider_custom_id"):
        op.drop_column("tree_analyses", column)
    op.execute("DROP SEQUENCE IF EXISTS tree_analysis_provider_custom_id_seq")
