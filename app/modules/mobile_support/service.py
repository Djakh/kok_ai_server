import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.errors.exceptions import AppError
from app.modules.mobile_support.models import (
    ContentReport,
    DeviceInstallation,
    TreeIssue,
    UserBlock,
)
from app.modules.mobile_support.schemas import (
    DevicePatchRequest,
    DeviceUpsertRequest,
    ReportCreateRequest,
    TreeIssueCreateRequest,
)
from app.modules.social.models import SocialPost, SocialPostComment
from app.modules.trees.models import Tree
from app.modules.uploads.models import UploadedAsset
from app.modules.users.models import User


class MobileSupportService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def device_payload(row: DeviceInstallation) -> dict:
        return {
            "installation_id": row.installation_id,
            "platform": row.platform,
            "locale": row.locale,
            "app_version": row.app_version,
            "last_seen_at": row.last_seen_at,
            "enabled": row.enabled,
            "token_last_four": row.push_token[-4:],
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def upsert_device(self, user_id: uuid.UUID, payload: DeviceUpsertRequest) -> DeviceInstallation:
        row = (
            self.db.query(DeviceInstallation)
            .filter(DeviceInstallation.installation_id == payload.installation_id)
            .first()
        )
        if row is None:
            row = DeviceInstallation(user_id=user_id, **payload.model_dump(exclude_none=True))
            self.db.add(row)
        else:
            if row.user_id != user_id:
                if row.push_token != payload.push_token:
                    raise AppError(
                        "installation_owner_conflict",
                        "Installation belongs to another user and the push token does not match.",
                        409,
                    )
                row.user_id = user_id
            for field, value in payload.model_dump(exclude_none=True).items():
                setattr(row, field, value)
        row.last_seen_at = payload.last_seen_at or datetime.now(timezone.utc)
        row.enabled = True
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(
                "device_token_conflict", "Push token belongs to another installation.", 409
            ) from exc
        self.db.refresh(row)
        return row

    def patch_device(
        self, user_id: uuid.UUID, installation_id: str, payload: DevicePatchRequest
    ) -> DeviceInstallation:
        row = self._owned_device(user_id, installation_id)
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(row, field, value)
        row.last_seen_at = payload.last_seen_at or datetime.now(timezone.utc)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(
                "device_token_conflict", "Push token belongs to another installation.", 409
            ) from exc
        self.db.refresh(row)
        return row

    def delete_device(self, user_id: uuid.UUID, installation_id: str) -> None:
        row = self._owned_device(user_id, installation_id)
        self.db.delete(row)
        self.db.commit()

    def _owned_device(self, user_id: uuid.UUID, installation_id: str) -> DeviceInstallation:
        row = (
            self.db.query(DeviceInstallation)
            .filter(
                DeviceInstallation.user_id == user_id,
                DeviceInstallation.installation_id == installation_id,
            )
            .first()
        )
        if not row:
            raise AppError("device_not_found", "Device installation was not found.", 404)
        return row

    def create_report(self, user_id: uuid.UUID, payload: ReportCreateRequest) -> ContentReport:
        model: Any = {
            "user": User,
            "post": SocialPost,
            "comment": SocialPostComment,
            "tree": Tree,
        }[payload.target_type]
        if self.db.query(model).filter(model.id == payload.target_id).first() is None:
            raise AppError("report_target_not_found", "Report target was not found.", 404)
        if payload.target_type == "user" and payload.target_id == user_id:
            raise AppError("invalid_report", "You cannot report yourself.", 422)
        row = ContentReport(reporter_user_id=user_id, **payload.model_dump())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def block_user(self, user_id: uuid.UUID, target_id: uuid.UUID) -> UserBlock:
        if user_id == target_id:
            raise AppError("invalid_block", "You cannot block yourself.", 422)
        if self.db.query(User).filter(User.id == target_id).first() is None:
            raise AppError("user_not_found", "User was not found.", 404)
        existing = (
            self.db.query(UserBlock)
            .filter(UserBlock.blocker_user_id == user_id, UserBlock.blocked_user_id == target_id)
            .first()
        )
        if existing:
            return existing
        row = UserBlock(blocker_user_id=user_id, blocked_user_id=target_id)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def unblock_user(self, user_id: uuid.UUID, target_id: uuid.UUID) -> None:
        self.db.query(UserBlock).filter(
            UserBlock.blocker_user_id == user_id, UserBlock.blocked_user_id == target_id
        ).delete()
        self.db.commit()

    def blocked_users(self, user_id: uuid.UUID) -> list[User]:
        return (
            self.db.query(User)
            .join(UserBlock, UserBlock.blocked_user_id == User.id)
            .filter(UserBlock.blocker_user_id == user_id)
            .order_by(UserBlock.created_at.desc())
            .all()
        )

    def create_tree_issue(
        self, user_id: uuid.UUID, tree_id: uuid.UUID, payload: TreeIssueCreateRequest
    ) -> TreeIssue:
        tree = self.db.query(Tree).filter(Tree.id == tree_id, Tree.deleted_at.is_(None)).first()
        if tree is None:
            raise AppError("tree_not_found", "Tree was not found.", 404)
        uploads: list[UploadedAsset] = []
        for upload_id in payload.upload_ids:
            asset = (
                self.db.query(UploadedAsset)
                .filter(UploadedAsset.id == upload_id, UploadedAsset.owner_user_id == user_id)
                .first()
            )
            if asset is None:
                raise AppError("invalid_upload", "An issue upload is missing or not owned.", 422)
            uploads.append(asset)
        row = TreeIssue(
            reporter_user_id=user_id,
            tree_id=tree_id,
            category=payload.category,
            notes=payload.notes,
            upload_ids=[str(value) for value in payload.upload_ids],
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
        self.db.add(row)
        for asset in uploads:
            asset.status = "attached"
            asset.attached_at = datetime.now(timezone.utc)
            asset.expires_at = None
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_tree_issues(self, user_id: uuid.UUID) -> list[TreeIssue]:
        return (
            self.db.query(TreeIssue)
            .filter(TreeIssue.reporter_user_id == user_id)
            .order_by(TreeIssue.created_at.desc())
            .all()
        )

    @staticmethod
    def report_payload(row: ContentReport) -> dict:
        return {
            "id": str(row.id),
            "target_type": row.target_type,
            "target_id": str(row.target_id),
            "reason": row.reason,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def issue_payload(row: TreeIssue) -> dict:
        return {
            "id": str(row.id),
            "tree_id": str(row.tree_id),
            "category": row.category,
            "notes": row.notes,
            "upload_ids": row.upload_ids,
            "location": (
                {"latitude": row.latitude, "longitude": row.longitude}
                if row.latitude is not None
                else None
            ),
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
