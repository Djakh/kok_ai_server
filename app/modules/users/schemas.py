from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    username: str
    full_name: str | None
    role: str
    bio: str | None
    avatar_url: str | None
    created_at: datetime


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    bio: str | None = Field(default=None, max_length=500)
    avatar_url: str | None = Field(default=None, max_length=512)


class UserSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    language_code: str
    privacy_profile_public: bool
    notifications_enabled: bool


class UserSettingsUpdateRequest(BaseModel):
    privacy_profile_public: bool | None = None
    notifications_enabled: bool | None = None


class LocalizationUpdateRequest(BaseModel):
    language_code: str
