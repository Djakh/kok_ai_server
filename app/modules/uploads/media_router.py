import uuid

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.common.config import get_settings
from app.common.db.session import get_db
from app.common.errors.exceptions import AppError
from app.common.storage.s3 import get_s3_client, verify_tree_analysis_image_signature
from app.modules.social.models import SocialPost, SocialPostImage
from app.modules.tree_analyses.models import TreeAnalysisImage
from app.modules.trees.models import Tree, TreeImage
from app.modules.uploads.models import UploadedAsset
from app.modules.users.models import User

router = APIRouter(prefix="/media", tags=["media"])


def _attached_analysis_image(
    db: Session,
    image_id: uuid.UUID,
) -> TreeAnalysisImage | None:
    return (
        db.query(TreeAnalysisImage)
        .join(Tree, Tree.analysis_id == TreeAnalysisImage.analysis_id)
        .filter(
            TreeAnalysisImage.id == image_id,
            Tree.deleted_at.is_(None),
        )
        .first()
    )


def _stream_object(storage_key: str, content_type: str) -> StreamingResponse:
    settings = get_settings()
    try:
        response = get_s3_client().get_object(
            Bucket=settings.s3_bucket,
            Key=storage_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise AppError("not_found", "Image not found", 404) from exc

    body = response["Body"]
    headers = {
        "Cache-Control": "private, max-age=900",
        "X-Content-Type-Options": "nosniff",
    }
    if response.get("ContentLength") is not None:
        headers["Content-Length"] = str(response["ContentLength"])
    if response.get("ETag"):
        headers["ETag"] = str(response["ETag"])
    return StreamingResponse(
        body.iter_chunks(chunk_size=64 * 1024),
        media_type=content_type,
        headers=headers,
        background=BackgroundTask(body.close),
    )


def _published_asset(db: Session, asset_id: uuid.UUID) -> UploadedAsset | None:
    asset = db.query(UploadedAsset).filter(UploadedAsset.id == asset_id).first()
    if not asset:
        return None

    social_image = (
        db.query(SocialPostImage.id)
        .join(SocialPost, SocialPost.id == SocialPostImage.post_id)
        .filter(
            SocialPostImage.uploaded_asset_id == asset_id,
            SocialPost.deleted_at.is_(None),
        )
        .first()
    )
    tree_image = (
        db.query(TreeImage.id)
        .join(Tree, Tree.id == TreeImage.tree_id)
        .filter(
            TreeImage.uploaded_asset_id == asset_id,
            Tree.deleted_at.is_(None),
            Tree.is_public.is_(True),
        )
        .first()
    )
    avatar = db.query(User.id).filter(User.avatar_asset_id == asset_id).first()
    return asset if social_image or tree_image or avatar else None


@router.get("/tree-analysis/{image_id}", include_in_schema=False)
def get_tree_analysis_media(
    image_id: uuid.UUID,
    expires: int,
    signature: str,
    db: Session = Depends(get_db),
):
    if not verify_tree_analysis_image_signature(image_id, expires, signature):
        raise AppError("not_found", "Image not found", 404)
    image = _attached_analysis_image(db, image_id)
    if not image:
        raise AppError("not_found", "Image not found", 404)
    return _stream_object(image.object_key, image.mime_type)


@router.get("/{asset_id}", include_in_schema=False)
def get_public_media(asset_id: uuid.UUID, db: Session = Depends(get_db)):
    """Stream a published image without exposing the private object-store address."""
    asset = _published_asset(db, asset_id)
    if not asset:
        raise AppError("not_found", "Image not found", 404)

    response = _stream_object(asset.storage_key, asset.content_type)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response
