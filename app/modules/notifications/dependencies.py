from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.notifications.service import NotificationService


def get_notification_service(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)
