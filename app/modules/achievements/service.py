import uuid

from sqlalchemy.orm import Session

from app.modules.achievements.repository import AchievementRepository


class AchievementService:
    def __init__(self, db: Session):
        self.repo = AchievementRepository(db)

    def list_for_user(self, user_id: uuid.UUID):
        return self.repo.list_for_user(user_id)
