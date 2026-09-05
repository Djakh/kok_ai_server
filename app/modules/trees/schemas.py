from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ConfirmedSpeciesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    candidate_id: UUID | None = None
    scientific_name: str = Field(min_length=1, max_length=255)
    common_name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def candidate_aliases_must_match(self):
        if self.id and self.candidate_id and self.id != self.candidate_id:
            raise ValueError("id and candidate_id must match when both are supplied")
        return self


class TreePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    visibility: Literal["private", "public"] | None = None
    confirmed_species: ConfirmedSpeciesRequest | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120, deprecated=True)

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one editable field is required")
        for field in ("nickname", "name", "visibility"):
            if field in self.model_fields_set and self.__dict__.get(field) is None:
                raise ValueError(f"{field} cannot be null")
        if self.nickname is not None and self.__dict__.get("name") is not None:
            raise ValueError("Send nickname or deprecated name, not both")
        if "confirmed_species" in self.model_fields_set and self.confirmed_species is None:
            raise ValueError("confirmed_species cannot be null")
        return self


class TreeCreateFromAnalysisRequest(BaseModel):
    analysis_id: UUID
    selected_candidate_id: UUID | None = None
    manual_scientific_name: str | None = Field(default=None, min_length=1, max_length=255)
    confirmed_species: ConfirmedSpeciesRequest | None = None
    location_evidence: LocationEvidence | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, gt=0)
    captured_at: datetime | None = None
    duplicate_check_status: Literal[
        "noNearbyTrees", "possibleMatches", "skippedDueToNetworkFailure"
    ] = "noNearbyTrees"
    nickname: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    visibility: Literal["private", "public"] = "private"

    @model_validator(mode="after")
    def validate_selection(self):
        if self.confirmed_species:
            candidate_id = self.confirmed_species.candidate_id or self.confirmed_species.id
            if candidate_id:
                self.selected_candidate_id = candidate_id
            elif not self.manual_scientific_name:
                self.manual_scientific_name = self.confirmed_species.scientific_name
        if self.selected_candidate_id and self.manual_scientific_name:
            raise ValueError(
                "selected_candidate_id and manual_scientific_name are mutually exclusive"
            )
        if self.location_evidence is None:
            if self.latitude is None or self.longitude is None:
                raise ValueError("location_evidence or latitude/longitude is required")
            accuracy = self.accuracy_meters or 1.0
            self.location_evidence = LocationEvidence(
                latitude=self.latitude,
                longitude=self.longitude,
                horizontal_accuracy_meters=accuracy,
                accepted_sample_count=3,
                rejected_sample_count=0,
                capture_duration_ms=1,
                best_sample_accuracy_meters=accuracy,
                captured_at=self.captured_at or datetime.now(timezone.utc),
                quality="poor" if self.accuracy_meters is None else "acceptable",
            )
        return self
