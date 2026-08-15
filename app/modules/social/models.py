import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db.base import Base, TimestampMixin, UUIDPKMixin


class SocialPost(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "social_posts"
    __table_args__ = (
        Index("ix_social_posts_author_created", "author_user_id", "created_at"),
        Index("ix_social_posts_location", "location", postgresql_using="gist"),
    )

    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tree_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trees.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    client_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SocialPostImage(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "social_post_images"

    post_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_posts.id"), nullable=False)
    uploaded_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uploaded_assets.id"), nullable=False
    )


class SocialPostLike(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "social_post_likes"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_social_like_user_post"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    post_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_posts.id"), nullable=False)


class SocialPostComment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "social_post_comments"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    post_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_posts.id"), nullable=False)
    content: Mapped[str] = mapped_column(String(500), nullable=False)
