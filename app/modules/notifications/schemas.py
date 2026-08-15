from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    title: str
    body: str
    is_read: bool
    created_at: datetime
