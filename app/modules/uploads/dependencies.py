from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.uploads.service import UploadService


def get_upload_service(db: Session = Depends(get_db)) -> UploadService:
    return UploadService(db)
