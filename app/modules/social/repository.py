import uuid
from datetime import datetime, timezone

from geoalchemy2.functions import ST_DWithin, ST_MakePoint
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.common.pagination.cursor import decode_cursor
from app.modules.social.models import SocialPost, SocialPostComment, SocialPostImage, SocialPostLike


class SocialRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_post(self, row: SocialPost) -> SocialPost:
        self.db.add(row)
        self.db.flush()
        return row

    def create_post_image(self, row: SocialPostImage) -> SocialPostImage:
        self.db.add(row)
        self.db.flush()
        return row

    def get_post(self, post_id: uuid.UUID) -> SocialPost | None:
        return self.db.query(SocialPost).filter(SocialPost.id == post_id, SocialPost.deleted_at.is_(None)).first()

    def list_posts(
        self,
        cursor: str | None,
        limit: int,
        user_id: uuid.UUID | None,
        near: tuple[float, float, float] | None,
    ) -> list[SocialPost]:
        q = self.db.query(SocialPost).filter(SocialPost.deleted_at.is_(None))
        if user_id:
            q = q.filter(SocialPost.author_user_id == user_id)
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

    def soft_delete_post(self, post: SocialPost) -> None:
        post.deleted_at = datetime.now(timezone.utc)
        self.db.add(post)

    def create_like(self, user_id: uuid.UUID, post_id: uuid.UUID) -> SocialPostLike:
        row = SocialPostLike(user_id=user_id, post_id=post_id)
        self.db.add(row)
        self.db.flush()
        return row

    def delete_like(self, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        self.db.query(SocialPostLike).filter(
            SocialPostLike.user_id == user_id, SocialPostLike.post_id == post_id
        ).delete()

    def likes(self, post_id: uuid.UUID) -> list[SocialPostLike]:
        return self.db.query(SocialPostLike).filter(SocialPostLike.post_id == post_id).all()

    def create_comment(self, row: SocialPostComment) -> SocialPostComment:
        self.db.add(row)
        self.db.flush()
        return row

    def list_comments(self, post_id: uuid.UUID) -> list[SocialPostComment]:
        return (
            self.db.query(SocialPostComment)
            .filter(SocialPostComment.post_id == post_id)
            .order_by(SocialPostComment.created_at.asc())
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
