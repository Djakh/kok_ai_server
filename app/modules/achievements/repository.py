import uuid

from sqlalchemy.orm import Session

from app.modules.achievements.models import Achievement, UserAchievement


class AchievementRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_user(self, user_id: uuid.UUID):
        return (
            self.db.query(Achievement)
            .join(UserAchievement, UserAchievement.achievement_id == Achievement.id)
            .filter(UserAchievement.user_id == user_id)
            .all()
        )
