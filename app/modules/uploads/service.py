import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.common.config import get_settings
from app.common.storage.s3 import upload_image
from app.common.tasks import image_post_process
from app.modules.uploads.models import UploadedAsset
from app.modules.uploads.repository import UploadRepository


class UploadService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UploadRepository(db)
        self.settings = get_settings()

    def upload_single(
        self, file: UploadFile, owner_id: uuid.UUID, purpose: str = "general"
    ) -> UploadedAsset:
        info = upload_image(file, str(owner_id))
        row = UploadedAsset(
            owner_user_id=owner_id,
            storage_key=str(info["key"]),
            original_storage_key=str(info["original_key"]),
            url=str(info["url"]),
            content_type=str(info["content_type"]),
            file_name=file.filename or "upload.bin",
            file_size=int(info["file_size"]),
            sha256=str(info["sha256"]),
            width=int(info["width"]),
            height=int(info["height"]),
            purpose=purpose,
            status="available",
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=self.settings.abandoned_upload_ttl_hours),
        )
        self.repo.create(row)
        self.db.commit()
        self.db.refresh(row)
        image_post_process.delay(str(row.id))
        return row

    def get_owned(self, upload_id: uuid.UUID, owner_id: uuid.UUID) -> UploadedAsset:
        row = self.repo.get(upload_id)
        from app.common.errors.exceptions import AppError

        if not row:
            raise AppError("not_found", "Upload not found", 404)
        if row.owner_user_id != owner_id:
            raise AppError("forbidden", "Access denied", 403)
        return row
