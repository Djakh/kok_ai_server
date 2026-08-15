import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.users.models import Follow, User, UserSettings


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(func.lower(User.email) == email.lower()).first()

    def get_by_username(self, username: str) -> User | None:
        return self.db.query(User).filter(func.lower(User.username) == username.lower()).first()

    def create(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user

    def get_settings(self, user_id: uuid.UUID) -> UserSettings | None:
        return self.db.query(UserSettings).filter(UserSettings.user_id == user_id).first()

    def upsert_settings(self, settings: UserSettings) -> UserSettings:
        self.db.add(settings)
        self.db.flush()
        return settings

    def follower_count(self, user_id: uuid.UUID) -> int:
        return self.db.query(Follow).filter(Follow.following_id == user_id).count()

    def following_count(self, user_id: uuid.UUID) -> int:
        return self.db.query(Follow).filter(Follow.follower_id == user_id).count()

    def list_followers(self, user_id: uuid.UUID) -> list[User]:
        return (
            self.db.query(User)
            .join(Follow, Follow.follower_id == User.id)
            .filter(Follow.following_id == user_id)
            .all()
        )

    def list_following(self, user_id: uuid.UUID) -> list[User]:
        return (
            self.db.query(User)
            .join(Follow, Follow.following_id == User.id)
            .filter(Follow.follower_id == user_id)
            .all()
        )

    def create_follow(self, follower_id: uuid.UUID, following_id: uuid.UUID) -> Follow:
        follow = Follow(follower_id=follower_id, following_id=following_id)
        self.db.add(follow)
        self.db.flush()
        return follow

    def delete_follow(self, follower_id: uuid.UUID, following_id: uuid.UUID) -> None:
        self.db.query(Follow).filter(
            Follow.follower_id == follower_id, Follow.following_id == following_id
        ).delete()
