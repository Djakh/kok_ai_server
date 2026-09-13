import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.common.enums.constants import SUPPORTED_LANGUAGES
from app.common.errors.exceptions import AppError
from app.common.security.password import verify_password
from app.common.storage.s3 import get_public_asset_url
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.notifications.models import Notification
from app.modules.social.models import SocialPost, SocialPostComment
from app.modules.trees.models import Tree
from app.modules.uploads.models import UploadedAsset
from app.modules.users.models import UserSettings
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    LocalizationUpdateRequest,
    UserSettingsUpdateRequest,
    UserUpdateRequest,
)


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    def update_me(self, user_id: uuid.UUID, payload: UserUpdateRequest):
        user = self.repo.get_by_id(user_id)
        if not user:
            raise AppError("not_found", "User not found", 404)
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(user, field, value)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_or_create_settings(self, user_id: uuid.UUID) -> UserSettings:
        settings = self.repo.get_settings(user_id)
        if settings:
            return settings
        settings = UserSettings(user_id=user_id)
        self.repo.upsert_settings(settings)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def update_settings(
        self, user_id: uuid.UUID, payload: UserSettingsUpdateRequest
    ) -> UserSettings:
        settings = self.get_or_create_settings(user_id)
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(settings, field, value)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def update_localization(
        self, user_id: uuid.UUID, payload: LocalizationUpdateRequest
    ) -> UserSettings:
        if payload.language_code not in SUPPORTED_LANGUAGES:
            raise AppError("invalid_language", "Unsupported language code", 422)
        settings = self.get_or_create_settings(user_id)
        settings.language_code = payload.language_code
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def follow(self, actor_id: uuid.UUID, target_id: uuid.UUID) -> None:
        if actor_id == target_id:
            raise AppError("invalid_follow", "Cannot follow yourself", 422)
        if not self.repo.get_by_id(target_id):
            raise AppError("not_found", "Target user not found", 404)
        try:
            self.repo.create_follow(actor_id, target_id)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise AppError("follow_exists", "Already following", 409) from exc

    def unfollow(self, actor_id: uuid.UUID, target_id: uuid.UUID) -> None:
        self.repo.delete_follow(actor_id, target_id)
        self.db.commit()

    def update_avatar(self, user_id: uuid.UUID, upload_id: uuid.UUID):
        user = self.repo.get_by_id(user_id)
        asset = (
            self.db.query(UploadedAsset)
            .filter(UploadedAsset.id == upload_id, UploadedAsset.owner_user_id == user_id)
            .first()
        )
        if not user or not asset:
            raise AppError("invalid_upload", "Avatar upload is missing or not owned.", 422)
        user.avatar_asset_id = asset.id
        user.avatar_url = get_public_asset_url(asset.id)
        asset.status = "attached"
        asset.attached_at = datetime.now(timezone.utc)
        asset.expires_at = None
        self.db.commit()
        self.db.refresh(user)
        return user

    def remove_avatar(self, user_id: uuid.UUID):
        user = self.repo.get_by_id(user_id)
        if not user:
            raise AppError("not_found", "User not found", 404)
        user.avatar_asset_id = None
        user.avatar_url = None
        self.db.commit()
        self.db.refresh(user)
        return user

    def deactivate(self, user_id: uuid.UUID, password: str) -> None:
        user = self._password_authorized_user(user_id, password)
        user.is_active = False
        user.deactivated_at = datetime.now(timezone.utc)
        RefreshTokenRepository(self.db).revoke_for_user(user.id)
        self.db.commit()

    def delete_account(self, user_id: uuid.UUID, password: str) -> None:
        user = self._password_authorized_user(user_id, password)
        suffix = str(user.id).replace("-", "")
        user.email = f"deleted+{suffix}@invalid.local"
        user.username = f"deleted_{suffix[:24]}"
        user.full_name = None
        user.bio = None
        user.avatar_url = None
        user.avatar_asset_id = None
        user.phone_number = None
        user.is_active = False
        user.deactivated_at = datetime.now(timezone.utc)
        RefreshTokenRepository(self.db).revoke_for_user(user.id)
        self.db.commit()

    def export_personal_data(self, user_id: uuid.UUID) -> dict:
        user = self.repo.get_by_id(user_id)
        if not user:
            raise AppError("not_found", "User not found", 404)
        settings = self.get_or_create_settings(user_id)
        trees = self.db.query(Tree).filter(Tree.owner_user_id == user_id).all()
        posts = self.db.query(SocialPost).filter(SocialPost.author_user_id == user_id).all()
        comments = (
            self.db.query(SocialPostComment).filter(SocialPostComment.user_id == user_id).all()
        )
        notifications = self.db.query(Notification).filter(Notification.user_id == user_id).all()
        return {
            "exported_at": datetime.now(timezone.utc),
            "schema_version": "1.0",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "bio": user.bio,
                "phone_number": user.phone_number,
                "created_at": user.created_at,
            },
            "settings": {
                "language_code": settings.language_code,
                "privacy_profile_public": settings.privacy_profile_public,
                "notifications_enabled": settings.notifications_enabled,
            },
            "trees": [
                {"id": str(row.id), "name": row.name, "created_at": row.created_at} for row in trees
            ],
            "posts": [
                {"id": str(row.id), "content": row.content, "created_at": row.created_at}
                for row in posts
            ],
            "comments": [
                {"id": str(row.id), "content": row.content, "created_at": row.created_at}
                for row in comments
            ],
            "notifications": [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "body": row.body,
                    "created_at": row.created_at,
                }
                for row in notifications
            ],
        }

    def _password_authorized_user(self, user_id: uuid.UUID, password: str):
        user = self.repo.get_by_id(user_id)
        if not user or not verify_password(password, user.password_hash):
            raise AppError("invalid_credentials", "Password is incorrect.", 401)
        return user
