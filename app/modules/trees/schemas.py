from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.tree_analyses.schemas import LocationEvidence


class GeoLocation(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(ge=0)


class TreeImageRefs(BaseModel):
    front: str
    trunk: str
    leaves: str


class TreeRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: GeoLocation
    images: TreeImageRefs
    captured_at: datetime


class TreePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = None


class TreeResponse(BaseModel):
    id: UUID
    name: str
    status: str
    owner_id: UUID
    captured_at: datetime
    created_at: datetime
    location: dict[str, float]
    images: dict[str, str]


class TreeVerifyRequest(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class TreeCreateFromAnalysisRequest(BaseModel):
    analysis_id: UUID
    selected_candidate_id: UUID | None = None
    manual_scientific_name: str | None = Field(default=None, min_length=1, max_length=255)
    location_evidence: LocationEvidence
    duplicate_check_status: str
    nickname: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    visibility: str = "private"

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selected_candidate_id and self.manual_scientific_name:
            raise ValueError("selected_candidate_id and manual_scientific_name are mutually exclusive")
        if self.duplicate_check_status not in {
            "noNearbyTrees", "possibleMatches", "skippedDueToNetworkFailure"
        }:
            raise ValueError("invalid duplicate_check_status")
        if self.visibility not in {"public", "private"}:
            raise ValueError("visibility must be public or private")
        return self
