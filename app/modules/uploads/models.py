import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db.base import Base, TimestampMixin, UUIDPKMixin


class UploadedAsset(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "uploaded_assets"
    __table_args__ = (
        Index("ix_uploaded_assets_owner_id", "owner_user_id"),
        Index("ix_uploaded_assets_created_at", "created_at"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    original_storage_key: Mapped[str | None] = mapped_column(String(512), unique=True)
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(32), default="general")
    status: Mapped[str] = mapped_column(String(24), default="available")
    attached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
