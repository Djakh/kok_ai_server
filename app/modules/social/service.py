import uuid
from datetime import datetime, timedelta, timezone

from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.errors.exceptions import AppError
from app.common.storage.s3 import get_public_asset_url
from app.modules.social.models import SocialPost, SocialPostComment, SocialPostImage, SocialPostLike
from app.modules.social.repository import SocialRepository
from app.modules.uploads.models import UploadedAsset
from app.modules.users.models import User


class SocialService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SocialRepository(db)
        self.viewer_id: uuid.UUID | None = None

    def _asset_for_owner(self, upload_id: str, owner_id: uuid.UUID) -> UploadedAsset:
        try:
            parsed = uuid.UUID(upload_id)
        except Exception as exc:
            raise AppError(
                "invalid_upload", "upload_id must be UUID from uploads API", 422
            ) from exc
        asset = self.db.query(UploadedAsset).filter(UploadedAsset.id == parsed).first()
        if not asset:
            raise AppError("upload_not_found", "Upload not found", 404)
        if asset.owner_user_id != owner_id:
            raise AppError("upload_forbidden", "Upload does not belong to user", 403)
        return asset

    def create_post(
        self,
        user_id: uuid.UUID,
        content: str,
        created_at,
        upload_id: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> SocialPost:
        if upload_id and len(upload_id) < 30:
            raise AppError(
                "local_path_not_allowed",
                "image_path from device is not accepted; upload first and send upload_id",
                422,
            )
        loc = None
        if latitude is not None and longitude is not None:
            loc = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
        post = SocialPost(
            author_user_id=user_id,
            content=content,
            client_created_at=created_at.astimezone(timezone.utc),
            location=loc,
        )
        self.repo.create_post(post)
        if upload_id:
            asset = self._asset_for_owner(upload_id, user_id)
            asset.attached_at = datetime.now(timezone.utc)
            asset.expires_at = None
            asset.status = "attached"
            self.repo.create_post_image(
                SocialPostImage(post_id=post.id, uploaded_asset_id=asset.id)
            )
        self.db.commit()
        self.db.refresh(post)
        return post

    def patch_post(
        self,
        post_id: uuid.UUID,
        user_id: uuid.UUID,
        content: str | None,
        remove_image: bool,
    ) -> SocialPost:
        post = self.repo.get_post(post_id)
        if not post:
            raise AppError("not_found", "Post not found", 404)
        if post.author_user_id != user_id:
            raise AppError("forbidden", "Not post owner", 403)
        if content is not None:
            post.content = content
        if remove_image:
            image = (
                self.db.query(SocialPostImage).filter(SocialPostImage.post_id == post.id).first()
            )
            if image:
                asset = (
                    self.db.query(UploadedAsset)
                    .filter(UploadedAsset.id == image.uploaded_asset_id)
                    .first()
                )
                self.db.delete(image)
                if asset:
                    asset.status = "available"
                    asset.attached_at = None
                    asset.expires_at = datetime.now(timezone.utc) + timedelta(
                        hours=get_settings().abandoned_upload_ttl_hours
                    )
        self.db.commit()
        self.db.refresh(post)
        return post

    def delete_post(self, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
        post = self.repo.get_post(post_id)
        if not post:
            raise AppError("not_found", "Post not found", 404)
        if post.author_user_id != user_id:
            raise AppError("forbidden", "Not post owner", 403)
        self.repo.soft_delete_post(post)
        self.db.commit()

    def post_payload(self, post: SocialPost) -> dict:
        row = self.db.execute(
            text(
                """
                SELECT ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
                FROM social_posts WHERE id=:post_id
                """
            ),
            {"post_id": post.id},
        ).first()
        loc: dict[str, float | None] = {"latitude": None, "longitude": None}
        if row and row.lat is not None:
            loc = {"latitude": float(row.lat), "longitude": float(row.lng)}
        images = (
            self.db.query(UploadedAsset)
            .join(SocialPostImage, SocialPostImage.uploaded_asset_id == UploadedAsset.id)
            .filter(SocialPostImage.post_id == post.id)
            .order_by(SocialPostImage.created_at.asc(), SocialPostImage.id.asc())
            .all()
        )
        image = images[0] if images else None
        author = self.db.query(User).filter(User.id == post.author_user_id).first()
        like_count = self.db.query(SocialPostLike).filter(SocialPostLike.post_id == post.id).count()
        comment_count = (
            self.db.query(SocialPostComment).filter(SocialPostComment.post_id == post.id).count()
        )
        liked_by_me = False
        if self.viewer_id:
            liked_by_me = (
                self.db.query(SocialPostLike)
                .filter(
                    SocialPostLike.post_id == post.id,
                    SocialPostLike.user_id == self.viewer_id,
                )
                .first()
                is not None
            )
        media = [
            {
                "id": str(item.id),
                "url": get_public_asset_url(item.id),
                "width": item.width,
                "height": item.height,
                "aspect_ratio": (
                    item.width / item.height
                    if item.width and item.height
                    else None
                ),
                "content_type": item.content_type,
            }
            for item in images
        ]
        return {
            "id": str(post.id),
            "author_id": str(post.author_user_id),
            "content": post.content,
            # Do not return the denormalized S3 URL. Old rows can contain an
            # internal/localhost endpoint, which is unreachable from a phone.
            "image_url": get_public_asset_url(image.id) if image else None,
            "image_width": image.width if image else None,
            "image_height": image.height if image else None,
            "image_aspect_ratio": (
                image.width / image.height
                if image and image.width and image.height
                else None
            ),
            "image": media[0] if media else None,
            "images": media,
            "location": loc,
            "created_at": post.created_at,
            "updated_at": post.updated_at,
            "author": {
                "id": str(author.id) if author else str(post.author_user_id),
                "username": author.username if author else "unknown",
                "full_name": author.full_name if author else None,
                "avatar_url": (
                    get_public_asset_url(author.avatar_asset_id)
                    if author and author.avatar_asset_id
                    else None
                ),
            },
            "like_count": like_count,
            "comment_count": comment_count,
            "liked_by_me": liked_by_me,
            "is_mine": self.viewer_id == post.author_user_id,
        }

    def comment_payload(self, comment: SocialPostComment) -> dict:
        author = self.db.query(User).filter(User.id == comment.user_id).first()
        return {
            "id": str(comment.id),
            "author_id": str(comment.user_id),
            "author": {
                "id": str(author.id) if author else str(comment.user_id),
                "username": author.username if author else "unknown",
                "full_name": author.full_name if author else None,
                "avatar_url": (
                    get_public_asset_url(author.avatar_asset_id)
                    if author and author.avatar_asset_id
                    else None
                ),
            },
            "post_id": str(comment.post_id),
            "content": comment.content,
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
            "like_count": 0,
            "liked_by_me": False,
            "is_mine": self.viewer_id == comment.user_id,
        }

    def add_like(self, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
        if not self.repo.get_post(post_id):
            raise AppError("not_found", "Post not found", 404)
        if self.repo.get_like(user_id, post_id):
            return
        try:
            self.repo.create_like(user_id, post_id)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            # A concurrent duplicate like has the same final state.
            if self.repo.get_like(user_id, post_id):
                return
            raise AppError("like_failed", "Could not like post", 409) from exc

    def remove_like(self, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
        if not self.repo.get_post(post_id):
            raise AppError("not_found", "Post not found", 404)
        self.repo.delete_like(user_id, post_id)
        self.db.commit()

    def add_comment(
        self, post_id: uuid.UUID, user_id: uuid.UUID, content: str
    ) -> SocialPostComment:
        if not self.repo.get_post(post_id):
            raise AppError("not_found", "Post not found", 404)
        row = SocialPostComment(post_id=post_id, user_id=user_id, content=content)
        self.repo.create_comment(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_comment(self, comment_id: uuid.UUID, user_id: uuid.UUID) -> None:
        row = self.repo.get_comment(comment_id)
        if not row:
            raise AppError("not_found", "Comment not found", 404)
        post = self.repo.get_post(row.post_id)
        if row.user_id != user_id and (not post or post.author_user_id != user_id):
            raise AppError("forbidden", "Not comment owner", 403)
        self.repo.delete_comment(comment_id)
        self.db.commit()
