import uuid
from datetime import datetime, timezone

from geoalchemy2.functions import ST_DWithin, ST_MakePoint
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.common.pagination.cursor import decode_cursor
from app.modules.mobile_support.models import UserBlock
from app.modules.social.models import SocialPost, SocialPostComment, SocialPostImage, SocialPostLike
from app.modules.users.models import Follow


class SocialRepository:
    def __init__(self, db: Session):
        self.db = db
        self.viewer_id: uuid.UUID | None = None

    def create_post(self, row: SocialPost) -> SocialPost:
        self.db.add(row)
        self.db.flush()
        return row

    def create_post_image(self, row: SocialPostImage) -> SocialPostImage:
        self.db.add(row)
        self.db.flush()
        return row

    def get_post(self, post_id: uuid.UUID) -> SocialPost | None:
        return (
            self.db.query(SocialPost)
            .filter(SocialPost.id == post_id, SocialPost.deleted_at.is_(None))
            .first()
        )

    def list_posts(
        self,
        cursor: str | None,
        limit: int,
        user_id: uuid.UUID | None,
        near: tuple[float, float, float] | None,
        following_only: bool = False,
    ) -> list[SocialPost]:
        q = self.db.query(SocialPost).filter(SocialPost.deleted_at.is_(None))
        if self.viewer_id:
            blocked_by_viewer = self.db.query(UserBlock.blocked_user_id).filter(
                UserBlock.blocker_user_id == self.viewer_id
            )
            viewers_blocking_me = self.db.query(UserBlock.blocker_user_id).filter(
                UserBlock.blocked_user_id == self.viewer_id
            )
            q = q.filter(
                SocialPost.author_user_id.not_in(blocked_by_viewer),
                SocialPost.author_user_id.not_in(viewers_blocking_me),
            )
        if user_id:
            q = q.filter(SocialPost.author_user_id == user_id)
        if following_only:
            if not self.viewer_id:
                return []
            followed_ids = self.db.query(Follow.following_id).filter(
                Follow.follower_id == self.viewer_id
            )
            q = q.filter(
                or_(
                    SocialPost.author_user_id == self.viewer_id,
                    SocialPost.author_user_id.in_(followed_ids),
                )
            )
        if near:
            lat, lng, radius = near
            q = q.filter(ST_DWithin(SocialPost.location, ST_MakePoint(lng, lat), radius))
        if cursor:
            created_at, item_id = decode_cursor(cursor)
            cur_uuid = uuid.UUID(item_id)
            q = q.filter(
                or_(
                    SocialPost.created_at < created_at,
                    and_(SocialPost.created_at == created_at, SocialPost.id < cur_uuid),
                )
            )
        return q.order_by(SocialPost.created_at.desc(), SocialPost.id.desc()).limit(limit).all()

    def count_posts(self, user_id: uuid.UUID) -> int:
        return (
            self.db.query(SocialPost)
            .filter(
                SocialPost.author_user_id == user_id,
                SocialPost.deleted_at.is_(None),
            )
            .count()
        )

    def soft_delete_post(self, post: SocialPost) -> None:
        post.deleted_at = datetime.now(timezone.utc)
        self.db.add(post)

    def create_like(self, user_id: uuid.UUID, post_id: uuid.UUID) -> SocialPostLike:
        row = SocialPostLike(user_id=user_id, post_id=post_id)
        self.db.add(row)
        self.db.flush()
        return row

    def get_like(self, user_id: uuid.UUID, post_id: uuid.UUID) -> SocialPostLike | None:
        return (
            self.db.query(SocialPostLike)
            .filter(
                SocialPostLike.user_id == user_id,
                SocialPostLike.post_id == post_id,
            )
            .first()
        )

    def delete_like(self, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        self.db.query(SocialPostLike).filter(
            SocialPostLike.user_id == user_id, SocialPostLike.post_id == post_id
        ).delete()

    def likes(
        self,
        post_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = 51,
    ) -> list[SocialPostLike]:
        q = self.db.query(SocialPostLike).filter(SocialPostLike.post_id == post_id)
        if cursor:
            created_at, item_id = decode_cursor(cursor)
            q = q.filter(
                or_(
                    SocialPostLike.created_at < created_at,
                    and_(
                        SocialPostLike.created_at == created_at,
                        SocialPostLike.id < uuid.UUID(item_id),
                    ),
                )
            )
        return (
            q.order_by(SocialPostLike.created_at.desc(), SocialPostLike.id.desc())
            .limit(limit)
            .all()
        )

    def create_comment(self, row: SocialPostComment) -> SocialPostComment:
        self.db.add(row)
        self.db.flush()
        return row

    def list_comments(
        self,
        post_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = 51,
    ) -> list[SocialPostComment]:
        q = self.db.query(SocialPostComment).filter(SocialPostComment.post_id == post_id)
        if cursor:
            created_at, item_id = decode_cursor(cursor)
            q = q.filter(
                or_(
                    SocialPostComment.created_at > created_at,
                    and_(
                        SocialPostComment.created_at == created_at,
                        SocialPostComment.id > uuid.UUID(item_id),
                    ),
                )
            )
        return (
            q.order_by(SocialPostComment.created_at.asc(), SocialPostComment.id.asc())
            .limit(limit)
            .all()
        )

    def get_comment(self, comment_id: uuid.UUID) -> SocialPostComment | None:
        return self.db.query(SocialPostComment).filter(SocialPostComment.id == comment_id).first()

    def delete_comment(self, comment_id: uuid.UUID) -> None:
        self.db.query(SocialPostComment).filter(SocialPostComment.id == comment_id).delete()

    def liked_posts(self, user_id: uuid.UUID) -> list[SocialPost]:
        return (
            self.db.query(SocialPost)
            .join(SocialPostLike, SocialPostLike.post_id == SocialPost.id)
            .filter(SocialPostLike.user_id == user_id, SocialPost.deleted_at.is_(None))
            .order_by(SocialPost.created_at.desc())
            .all()
        )
