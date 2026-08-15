from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.achievements.service import AchievementService


def get_achievement_service(db: Session = Depends(get_db)) -> AchievementService:
    return AchievementService(db)
