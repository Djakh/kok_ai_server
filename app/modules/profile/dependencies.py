from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.profile.service import ProfileService


def get_profile_service(db: Session = Depends(get_db)) -> ProfileService:
    return ProfileService(db)
