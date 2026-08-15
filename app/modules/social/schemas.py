from datetime import datetime

from pydantic import BaseModel, Field


class OptionalLocation(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class SocialCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    image_path: str | None = None
    location: OptionalLocation
    created_at: datetime


class SocialCreateByUploadRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    image_path: str | None = None
    upload_id: str | None = None
    location: OptionalLocation
    created_at: datetime


class SocialPatchRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class CommentCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500)
