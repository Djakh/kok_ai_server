"""Mobile product contract: devices, safety, recovery, and account lifecycle.

Revision ID: 20260821_0006
Revises: 20260815_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260821_0006"
down_revision: str | None = "20260815_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_asset_id", postgresql.UUID(as_uuid=True)))
    op.add_column("users", sa.Column("phone_number", sa.String(32)))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_users_avatar_asset_id_uploaded_assets",
        "users",
        "uploaded_assets",
        ["avatar_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_users_phone_number", "users", ["phone_number"])

    op.create_table(
        "verification_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("destination", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("reset_token_hash", sa.String(64), unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_verification_destination_purpose",
        "verification_challenges",
        ["destination", "purpose", "created_at"],
    )

    op.create_table(
        "device_installations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("installation_id", sa.String(160), nullable=False),
        sa.Column("push_token", sa.String(512), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("app_version", sa.String(40), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "installation_id", name="uq_device_user_installation"),
    )
    op.create_index("ix_device_push_token", "device_installations", ["push_token"], unique=True)

    op.create_table(
        "content_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reporter_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_content_reports_reporter_created",
        "content_reports",
        ["reporter_user_id", "created_at"],
    )

    op.create_table(
        "user_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("blocker_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("blocked_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("blocker_user_id", "blocked_user_id", name="uq_user_block_pair"),
    )
    op.create_index("ix_user_blocks_blocker", "user_blocks", ["blocker_user_id"])

    op.create_table(
        "tree_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reporter_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("upload_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("status", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_tree_issues_reporter_created", "tree_issues", ["reporter_user_id", "created_at"]
    )
    op.create_index("ix_tree_issues_tree", "tree_issues", ["tree_id"])


def downgrade() -> None:
    op.drop_table("tree_issues")
    op.drop_table("user_blocks")
    op.drop_table("content_reports")
    op.drop_table("device_installations")
    op.drop_table("verification_challenges")
    op.drop_constraint("uq_users_phone_number", "users", type_="unique")
    op.drop_constraint("fk_users_avatar_asset_id_uploaded_assets", "users", type_="foreignkey")
    for name in (
        "deactivated_at",
        "phone_verified_at",
        "email_verified_at",
        "phone_number",
        "avatar_asset_id",
    ):
        op.drop_column("users", name)
