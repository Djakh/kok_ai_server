from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_id: str = Field(min_length=8, max_length=160)
    push_token: str = Field(min_length=16, max_length=512)
    platform: Literal["ios", "android"]
    locale: str = Field(min_length=2, max_length=16)
    app_version: str = Field(min_length=1, max_length=40)
    last_seen_at: datetime | None = None


class DevicePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    push_token: str | None = Field(default=None, min_length=16, max_length=512)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    app_version: str | None = Field(default=None, min_length=1, max_length=40)
    enabled: bool | None = None
    last_seen_at: datetime | None = None


class ReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["user", "post", "comment", "tree"]
    target_id: UUID
    reason: Literal[
        "spam", "harassment", "hate", "misinformation", "unsafe_content", "privacy", "other"
    ]
    details: str | None = Field(default=None, max_length=2000)


class TreeIssueCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "damage", "disease", "hazard", "incorrect_location", "incorrect_species", "other"
    ]
    notes: str | None = Field(default=None, max_length=2000)
    upload_ids: list[UUID] = Field(default_factory=list, max_length=5)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("longitude")
    @classmethod
    def coordinates_are_paired(cls, value: float | None, info):  # noqa: ANN001
        latitude = info.data.get("latitude")
        if (latitude is None) != (value is None):
            raise ValueError("latitude and longitude must be supplied together")
        return value
