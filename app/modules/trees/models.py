import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db.base import Base, TimestampMixin, UUIDPKMixin


class TreeStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class TreeImageKind(str, enum.Enum):
    FRONT = "front"
    TRUNK = "trunk"
    LEAVES = "leaves"


class TreeEventType(str, enum.Enum):
    REGISTERED = "registered"
    UPDATED = "updated"
    VERIFIED = "verified"


class Tree(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "trees"
    __table_args__ = (
        Index("ix_trees_owner_user_id", "owner_user_id"),
        Index("ix_trees_owner_created_id", "owner_user_id", "created_at", "id"),
        Index("ix_trees_created_id", "created_at", "id"),
        Index("ix_trees_status", "status"),
        Index("ix_trees_ai_status", "ai_status"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[TreeStatus] = mapped_column(Enum(TreeStatus), default=TreeStatus.PENDING, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ai_status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    ai_model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ai_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_species: Mapped[str | None] = mapped_column(String(255), nullable=True)
    candidate_species: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_health_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tree_analyses.id"), unique=True
    )
    selected_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tree_analysis_candidates.id")
    )
    manual_scientific_name: Mapped[str | None] = mapped_column(String(255))
    identification_source: Mapped[str] = mapped_column(String(32), default="unknown")
    duplicate_check_status: Mapped[str | None] = mapped_column(String(40))


class TreeImage(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tree_images"

    tree_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trees.id"), nullable=False)
    uploaded_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uploaded_assets.id"), nullable=False
    )
    kind: Mapped[TreeImageKind] = mapped_column(Enum(TreeImageKind), nullable=False)


class TreeLocation(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tree_locations"
    __table_args__ = (
        Index("ix_tree_locations_tree_id", "tree_id"),
        Index("ix_tree_locations_geom", "location", postgresql_using="gist"),
    )

    tree_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trees.id"), unique=True)
    location: Mapped[str] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    accuracy_meters: Mapped[float] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="mobile", nullable=False)
    accepted_sample_count: Mapped[int | None] = mapped_column(Integer)
    rejected_sample_count: Mapped[int | None] = mapped_column(Integer)
    capture_duration_ms: Mapped[int | None] = mapped_column(Integer)
    best_sample_accuracy_meters: Mapped[float | None] = mapped_column(Float)
    evidence_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality: Mapped[str | None] = mapped_column(String(16))


class TreeEvent(UUIDPKMixin, Base):
    __tablename__ = "tree_events"
    __table_args__ = (Index("ix_tree_events_tree_id_created", "tree_id", "created_at"),)

    tree_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trees.id"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    event_type: Mapped[TreeEventType] = mapped_column(Enum(TreeEventType), nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
