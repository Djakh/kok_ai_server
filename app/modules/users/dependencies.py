from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.users.service import UserService


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(db)
