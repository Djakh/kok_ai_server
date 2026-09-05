import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db.base import Base, TimestampMixin, UUIDPKMixin


class DeviceInstallation(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "device_installations"
    __table_args__ = (
        UniqueConstraint("installation_id", name="uq_device_installation_id"),
        Index("ix_device_push_token", "push_token", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    installation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    push_token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    app_version: Mapped[str] = mapped_column(String(40), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ContentReport(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "content_reports"
    __table_args__ = (
        Index("ix_content_reports_reporter_created", "reporter_user_id", "created_at"),
    )

    reporter_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="submitted", nullable=False)


class UserBlock(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_user_id", "blocked_user_id", name="uq_user_block_pair"),
        Index("ix_user_blocks_blocker", "blocker_user_id"),
    )

    blocker_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    blocked_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class TreeIssue(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tree_issues"
    __table_args__ = (
        Index("ix_tree_issues_reporter_created", "reporter_user_id", "created_at"),
        Index("ix_tree_issues_tree", "tree_id"),
    )

    reporter_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    tree_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trees.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    upload_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="submitted", nullable=False)
