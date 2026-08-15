from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UploadedAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    content_type: str
    file_name: str
    file_size: int
    created_at: datetime
