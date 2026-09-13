from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.common.storage.s3 import get_public_asset_url


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    username: str
    full_name: str | None
    role: str
    bio: str | None
    avatar_url: str | None
    avatar_asset_id: UUID | None = Field(default=None, exclude=True)
    created_at: datetime

    @model_validator(mode="after")
    def use_mobile_reachable_avatar_url(self) -> "UserPublic":
        if self.avatar_asset_id:
            self.avatar_url = get_public_asset_url(self.avatar_asset_id)
        return self


class UserMe(UserPublic):
    email_verified_at: datetime | None = None
    phone_number: str | None = None
    phone_verified_at: datetime | None = None


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
    model_config = ConfigDict(extra="forbid")

    privacy_profile_public: bool | None = None
    notifications_enabled: bool | None = None


class LocalizationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_code: Literal["en", "ru", "uz"]


class AvatarUpdateRequest(BaseModel):
    upload_id: UUID


class AccountDeleteRequest(BaseModel):
    password: str
