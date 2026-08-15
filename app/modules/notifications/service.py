import uuid

from sqlalchemy.orm import Session

from app.common.errors.exceptions import AppError
from app.modules.notifications.repository import NotificationRepository


class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationRepository(db)

    def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> None:
        row = self.repo.get(notification_id)
        if not row:
            raise AppError("not_found", "Notification not found", 404)
        if row.user_id != user_id:
            raise AppError("forbidden", "Access denied", 403)
        row.is_read = True
        self.db.commit()

    def mark_all_read(self, user_id: uuid.UUID) -> int:
        count = self.repo.read_all(user_id)
        self.db.commit()
        return count
