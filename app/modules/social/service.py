import uuid
from datetime import datetime, timezone

from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.errors.exceptions import AppError
from app.modules.social.models import SocialPost, SocialPostComment, SocialPostImage
from app.modules.social.repository import SocialRepository
from app.modules.uploads.models import UploadedAsset


class SocialService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SocialRepository(db)

    def _asset_for_owner(self, upload_id: str, owner_id: uuid.UUID) -> UploadedAsset:
        try:
            parsed = uuid.UUID(upload_id)
        except Exception as exc:
            raise AppError("invalid_upload", "upload_id must be UUID from uploads API", 422) from exc
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
            self.repo.create_post_image(SocialPostImage(post_id=post.id, uploaded_asset_id=asset.id))
        self.db.commit()
        self.db.refresh(post)
        return post

    def patch_post(self, post_id: uuid.UUID, user_id: uuid.UUID, content: str) -> SocialPost:
        post = self.repo.get_post(post_id)
        if not post:
            raise AppError("not_found", "Post not found", 404)
        if post.author_user_id != user_id:
            raise AppError("forbidden", "Not post owner", 403)
        post.content = content
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
        image = (
            self.db.query(UploadedAsset)
            .join(SocialPostImage, SocialPostImage.uploaded_asset_id == UploadedAsset.id)
            .filter(SocialPostImage.post_id == post.id)
            .first()
        )
        return {
            "id": str(post.id),
            "author_id": str(post.author_user_id),
            "content": post.content,
            "image_url": image.url if image else None,
            "location": loc,
            "created_at": post.created_at,
        }

    def add_like(self, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
        try:
            self.repo.create_like(user_id, post_id)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise AppError("already_liked", "Like already exists", 409) from exc

    def remove_like(self, post_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.repo.delete_like(user_id, post_id)
        self.db.commit()

    def add_comment(self, post_id: uuid.UUID, user_id: uuid.UUID, content: str) -> SocialPostComment:
        row = SocialPostComment(post_id=post_id, user_id=user_id, content=content)
        self.repo.create_comment(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_comment(self, comment_id: uuid.UUID, user_id: uuid.UUID) -> None:
        row = self.repo.get_comment(comment_id)
        if not row:
            raise AppError("not_found", "Comment not found", 404)
        if row.user_id != user_id:
            raise AppError("forbidden", "Not comment owner", 403)
        self.repo.delete_comment(comment_id)
        self.db.commit()
