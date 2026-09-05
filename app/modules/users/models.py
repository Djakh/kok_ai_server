import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db.base import Base, TimestampMixin, UUIDPKMixin


class UserRole(str, enum.Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    avatar_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uploaded_assets.id", ondelete="SET NULL"), nullable=True
    )
    phone_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserSettings(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True
    )
    language_code: Mapped[str] = mapped_column(String(2), default="en", nullable=False)
    privacy_profile_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship("User")


class Follow(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("follower_id", "following_id", name="uq_follows_pair"),)

    follower_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    following_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class AuditLog(UUIDPKMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(120), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
