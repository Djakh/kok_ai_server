import uuid

from sqlalchemy.orm import Session

from app.common.enums.constants import SUPPORTED_LANGUAGES
from app.common.errors.exceptions import AppError
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

    def update_settings(self, user_id: uuid.UUID, payload: UserSettingsUpdateRequest) -> UserSettings:
        settings = self.get_or_create_settings(user_id)
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(settings, field, value)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def update_localization(self, user_id: uuid.UUID, payload: LocalizationUpdateRequest) -> UserSettings:
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
