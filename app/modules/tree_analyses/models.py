import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db.base import Base, TimestampMixin, UUIDPKMixin


class TreeAnalysis(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tree_analyses"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_tree_analyses_owner_idempotency"),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
            name="tree_analysis_coordinate_pair",
        ),
        Index("ix_tree_analyses_owner_created", "owner_user_id", "created_at"),
        Index("ix_tree_analyses_status", "status"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    normalized_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provider_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    numeric_provider_custom_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    location_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provider_name: Mapped[str] = mapped_column(String(64), default="kindwise_plant_id")
    provider_is_plant_binary: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provider_is_plant_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_mode: Mapped[str] = mapped_column(String(8), default="off")


class TreeAnalysisImage(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tree_analysis_images"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="tree_analysis_image_byte_size"),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png')", name="tree_analysis_image_mime"
        ),
        Index("ix_tree_analysis_images_analysis", "analysis_id"),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tree_analyses.id", ondelete="CASCADE"), nullable=False
    )
    organ: Mapped[str] = mapped_column(String(16), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_object_key: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TreeAnalysisCandidate(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tree_analysis_candidates"
    __table_args__ = (
        UniqueConstraint("analysis_id", "ordinal", name="uq_analysis_candidate_ordinal"),
        Index("ix_analysis_candidates_analysis", "analysis_id"),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tree_analyses.id", ondelete="CASCADE"), nullable=False
    )
    provider_taxon_id: Mapped[str | None] = mapped_column(String(160))
    scientific_name: Mapped[str] = mapped_column(String(255), nullable=False)
    common_name: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    genus: Mapped[str | None] = mapped_column(String(255))
    family: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    representative_image_url: Mapped[str | None] = mapped_column(Text)
    image_source_url: Mapped[str | None] = mapped_column(Text)
    attribution_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class IdempotencyRecord(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("principal_id", "method", "route", "key", name="uq_idempotency_scope"),
        Index("ix_idempotency_expiry", "expires_at"),
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TreeScan(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tree_scans"
    __table_args__ = (
        UniqueConstraint("analysis_id", name="uq_tree_scans_analysis_id"),
        CheckConstraint(
            "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180",
            name="tree_scan_coordinates",
        ),
        Index("ix_tree_scans_tree_analyzed", "tree_id", "analyzed_at"),
    )

    tree_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trees.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tree_analyses.id"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    health_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
