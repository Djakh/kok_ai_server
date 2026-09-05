from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.mobile_support.service import MobileSupportService


def get_mobile_support_service(db: Session = Depends(get_db)) -> MobileSupportService:
    return MobileSupportService(db)
