import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LocationEvidence(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "latitude": 41.299503,
                "longitude": 69.240098,
                "horizontal_accuracy_meters": 5.8,
                "accepted_sample_count": 8,
                "rejected_sample_count": 2,
                "capture_duration_ms": 12000,
                "best_sample_accuracy_meters": 4.2,
                "captured_at": "2026-08-15T05:00:12Z",
                "quality": "acceptable",
            }
        }
    )
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    horizontal_accuracy_meters: float = Field(gt=0)
    accepted_sample_count: int = Field(ge=1)
    rejected_sample_count: int = Field(ge=0)
    capture_duration_ms: int = Field(gt=0)
    best_sample_accuracy_meters: float = Field(gt=0)
    captured_at: datetime
    quality: Literal["excellent", "acceptable", "poor"]

    @field_validator("latitude", "longitude", "horizontal_accuracy_meters", "best_sample_accuracy_meters")
    @classmethod
    def finite_numbers(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @field_validator("captured_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        return value


class CandidatePayload(BaseModel):
    id: UUID
    common_name: str | None
    scientific_name: str
    confidence: float = Field(ge=0, le=1)
    genus: str | None
    family: str | None
    description: str | None
    representative_image_url: str | None
    image_source_url: str | None


class HealthPayload(BaseModel):
    status: Literal["likely_healthy", "possible_issue"]
    confidence: float = Field(ge=0, le=1)
    summary: str | None


class AnalysisPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "8a3f0ca0-d4d1-4ba1-b65e-918b16eec918",
                "provider": "kindwise_plant_id",
                "analyzed_at": "2026-08-15T05:00:25Z",
                "candidates": [],
                "health": None,
            }
        }
    )
    id: UUID
    provider: Literal["kindwise_plant_id"]
    analyzed_at: datetime
    candidates: list[CandidatePayload]
    health: HealthPayload | None


class AnalysisEnvelope(BaseModel):
    success: bool = True
    data: AnalysisPayload
    error: None = None
    meta: dict[str, Any] | None = None
