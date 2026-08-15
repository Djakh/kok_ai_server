"""add explicit tree privacy and persistence constraints

Revision ID: 20260810_0004
Revises: 20260806_0003
Create Date: 2026-08-10 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0004"
down_revision: str | None = "20260806_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing legacy profiles remain public; provider-created profiles explicitly set this false.
    op.add_column(
        "trees",
        sa.Column("is_public", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.alter_column("trees", "is_public", server_default=sa.false())
    op.create_index("ix_trees_created_id", "trees", ["created_at", "id"])
    op.create_index(
        "ix_trees_owner_created_id", "trees", ["owner_user_id", "created_at", "id"]
    )

    op.create_check_constraint(
        "tree_analysis_coordinate_pair",
        "tree_analyses",
        "(latitude IS NULL AND longitude IS NULL) OR "
        "(latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
    )
    op.create_check_constraint(
        "tree_analysis_image_byte_size",
        "tree_analysis_images",
        "byte_size > 0",
    )
    op.create_check_constraint(
        "tree_analysis_image_mime",
        "tree_analysis_images",
        "mime_type IN ('image/jpeg', 'image/png')",
    )
    op.create_check_constraint(
        "tree_scan_coordinates",
        "tree_scans",
        "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tree_scans_tree_scan_coordinates", "tree_scans", type_="check")
    op.drop_constraint(
        "ck_tree_analysis_images_tree_analysis_image_mime",
        "tree_analysis_images",
        type_="check",
    )
    op.drop_constraint(
        "ck_tree_analysis_images_tree_analysis_image_byte_size",
        "tree_analysis_images",
        type_="check",
    )
    op.drop_constraint(
        "ck_tree_analyses_tree_analysis_coordinate_pair",
        "tree_analyses",
        type_="check",
    )
    op.drop_index("ix_trees_owner_created_id", table_name="trees")
    op.drop_index("ix_trees_created_id", table_name="trees")
    op.drop_column("trees", "is_public")
