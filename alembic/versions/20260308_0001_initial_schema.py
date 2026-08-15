"""initial schema

Revision ID: 20260308_0001
Revises: None
Create Date: 2026-03-08 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260308_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None



def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    user_role = postgresql.ENUM(
        "USER",
        "MODERATOR",
        "ADMIN",
        name="userrole",
        create_type=False,
    )
    user_role.create(op.get_bind(), checkfirst=True)

    tree_status = postgresql.ENUM(
        "PENDING",
        "VERIFIED",
        "REJECTED",
        name="treestatus",
        create_type=False,
    )
    tree_status.create(op.get_bind(), checkfirst=True)

    tree_image_kind = postgresql.ENUM(
        "FRONT",
        "TRUNK",
        "LEAVES",
        name="treeimagekind",
        create_type=False,
    )
    tree_image_kind.create(op.get_bind(), checkfirst=True)

    tree_event_type = postgresql.ENUM(
        "REGISTERED",
        "UPDATED",
        "VERIFIED",
        name="treeeventtype",
        create_type=False,
    )
    tree_event_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)

    op.create_table(
        "achievements",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon_url", sa.String(length=512), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_achievements")),
        sa.UniqueConstraint("code", name=op.f("uq_achievements_code")),
    )

    op.create_table(
        "user_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("privacy_profile_public", sa.Boolean(), nullable=False),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_settings_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_settings")),
        sa.UniqueConstraint("user_id", name=op.f("uq_user_settings_user_id")),
    )

    op.create_table(
        "follows",
        sa.Column("follower_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("following_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"], name=op.f("fk_follows_follower_id_users")),
        sa.ForeignKeyConstraint(["following_id"], ["users.id"], name=op.f("fk_follows_following_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follows")),
        sa.UniqueConstraint("follower_id", "following_id", name="uq_follows_pair"),
    )

    op.create_table(
        "uploaded_assets",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("fk_uploaded_assets_owner_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploaded_assets")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_uploaded_assets_storage_key")),
    )
    op.create_index("ix_uploaded_assets_owner_id", "uploaded_assets", ["owner_user_id"], unique=False)
    op.create_index("ix_uploaded_assets_created_at", "uploaded_assets", ["created_at"], unique=False)

    op.create_table(
        "trees",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", tree_status, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_trees_owner_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trees")),
    )
    op.create_index("ix_trees_owner_user_id", "trees", ["owner_user_id"], unique=False)
    op.create_index("ix_trees_status", "trees", ["status"], unique=False)

    op.create_table(
        "tree_images",
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", tree_image_kind, nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tree_id"], ["trees.id"], name=op.f("fk_tree_images_tree_id_trees")),
        sa.ForeignKeyConstraint(
            ["uploaded_asset_id"], ["uploaded_assets.id"], name=op.f("fk_tree_images_uploaded_asset_id_uploaded_assets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tree_images")),
    )

    op.create_table(
        "tree_locations",
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location", Geography(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("accuracy_meters", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tree_id"], ["trees.id"], name=op.f("fk_tree_locations_tree_id_trees")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tree_locations")),
        sa.UniqueConstraint("tree_id", name=op.f("uq_tree_locations_tree_id")),
    )
    op.create_index("ix_tree_locations_tree_id", "tree_locations", ["tree_id"], unique=False)
    op.create_index("ix_tree_locations_geom", "tree_locations", ["location"], unique=False, postgresql_using="gist")

    op.create_table(
        "tree_events",
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", tree_event_type, nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_tree_events_actor_user_id_users")),
        sa.ForeignKeyConstraint(["tree_id"], ["trees.id"], name=op.f("fk_tree_events_tree_id_trees")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tree_events")),
    )
    op.create_index("ix_tree_events_tree_id_created", "tree_events", ["tree_id", "created_at"], unique=False)

    op.create_table(
        "social_posts",
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("location", Geography(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], name=op.f("fk_social_posts_author_user_id_users")),
        sa.ForeignKeyConstraint(["tree_id"], ["trees.id"], name=op.f("fk_social_posts_tree_id_trees")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_posts")),
    )
    op.create_index("ix_social_posts_author_created", "social_posts", ["author_user_id", "created_at"], unique=False)
    op.create_index("ix_social_posts_location", "social_posts", ["location"], unique=False, postgresql_using="gist")

    op.create_table(
        "social_post_images",
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["social_posts.id"], name=op.f("fk_social_post_images_post_id_social_posts")),
        sa.ForeignKeyConstraint(
            ["uploaded_asset_id"], ["uploaded_assets.id"], name=op.f("fk_social_post_images_uploaded_asset_id_uploaded_assets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_post_images")),
    )

    op.create_table(
        "social_post_likes",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["social_posts.id"], name=op.f("fk_social_post_likes_post_id_social_posts")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_social_post_likes_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_post_likes")),
        sa.UniqueConstraint("user_id", "post_id", name="uq_social_like_user_post"),
    )

    op.create_table(
        "social_post_comments",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.String(length=500), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["social_posts.id"], name=op.f("fk_social_post_comments_post_id_social_posts")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_social_post_comments_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_post_comments")),
    )

    op.create_table(
        "notifications",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "user_achievements",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["achievement_id"], ["achievements.id"], name=op.f("fk_user_achievements_achievement_id_achievements")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_achievements_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_achievements")),
        sa.UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=120), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_audit_logs_actor_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)



def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("user_achievements")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("social_post_comments")
    op.drop_table("social_post_likes")
    op.drop_table("social_post_images")
    op.drop_index("ix_social_posts_location", table_name="social_posts", postgresql_using="gist")
    op.drop_index("ix_social_posts_author_created", table_name="social_posts")
    op.drop_table("social_posts")
    op.drop_index("ix_tree_events_tree_id_created", table_name="tree_events")
    op.drop_table("tree_events")
    op.drop_index("ix_tree_locations_geom", table_name="tree_locations", postgresql_using="gist")
    op.drop_index("ix_tree_locations_tree_id", table_name="tree_locations")
    op.drop_table("tree_locations")
    op.drop_table("tree_images")
    op.drop_index("ix_trees_status", table_name="trees")
    op.drop_index("ix_trees_owner_user_id", table_name="trees")
    op.drop_table("trees")
    op.drop_index("ix_uploaded_assets_created_at", table_name="uploaded_assets")
    op.drop_index("ix_uploaded_assets_owner_id", table_name="uploaded_assets")
    op.drop_table("uploaded_assets")
    op.drop_table("follows")
    op.drop_table("user_settings")
    op.drop_table("achievements")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    sa.Enum(name="treeeventtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="treeimagekind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="treestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="userrole").drop(op.get_bind(), checkfirst=True)
