from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UploadedAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    content_type: str
    file_name: str
    file_size: int
    width: int | None
    height: int | None
    purpose: Literal["general", "avatar", "social_post", "tree_issue"]
    status: Literal["available", "attached"]
    attached_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
