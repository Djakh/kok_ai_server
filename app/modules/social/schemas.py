from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OptionalLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates_are_paired(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be null")
        return self


class SocialCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    image_path: str | None = None
    location: OptionalLocation = Field(default_factory=OptionalLocation)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value


class SocialCreateByUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2000)
    image_path: str | None = None
    upload_id: str | None = None
    location: OptionalLocation = Field(default_factory=OptionalLocation)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value


class SocialPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=2000)
    remove_image: bool = False

    @model_validator(mode="after")
    def has_change(self):
        if self.content is None and not self.remove_image:
            raise ValueError("Send content and/or remove_image=true")
        return self


class CommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=500)
