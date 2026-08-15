from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.social.service import SocialService


def get_social_service(db: Session = Depends(get_db)) -> SocialService:
    return SocialService(db)
