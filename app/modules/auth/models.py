import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db.base import Base, UUIDPKMixin


class RefreshToken(UUIDPKMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerificationChallenge(UUIDPKMixin, Base):
    __tablename__ = "verification_challenges"
    __table_args__ = (
        Index("ix_verification_destination_purpose", "destination", "purpose", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
