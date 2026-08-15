import uuid

from sqlalchemy.orm import Session

from app.modules.uploads.models import UploadedAsset


class UploadRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, row: UploadedAsset) -> UploadedAsset:
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, asset_id: uuid.UUID) -> UploadedAsset | None:
        return self.db.query(UploadedAsset).filter(UploadedAsset.id == asset_id).first()
