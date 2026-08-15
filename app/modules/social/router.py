import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.common.db.session import get_db
from app.common.errors.exceptions import AppError
from app.common.idempotency.service import (
    get_body_hash,
    get_multipart_hash,
    get_replayed_response,
    save_response,
)
from app.common.pagination.cursor import encode_cursor
from app.common.rate_limit.dependencies import WriteRateLimit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.social.constants import DEFAULT_POST_LIMIT, MAX_POST_LIMIT
from app.modules.social.dependencies import get_social_service
from app.modules.social.repository import SocialRepository
from app.modules.social.schemas import (
    CommentCreateRequest,
    SocialCreateByUploadRequest,
    SocialPatchRequest,
)
from app.modules.social.service import SocialService
from app.modules.uploads.service import UploadService

router = APIRouter(prefix="/social", tags=["social"])


@router.post("/posts", dependencies=[WriteRateLimit])
async def create_post(
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: SocialService = Depends(get_social_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body_hash = await get_body_hash(request)
        if idempotency_key:
            replay = get_replayed_response(str(current.user.id), idempotency_key, body_hash)
            if replay:
                return success_response(replay)
        request_payload = SocialCreateByUploadRequest.model_validate(await request.json())
        upload_ref = request_payload.upload_id or request_payload.image_path
        post = service.create_post(
            user_id=current.user.id,
            content=request_payload.content,
            created_at=request_payload.created_at,
            upload_id=upload_ref,
            latitude=request_payload.location.latitude,
            longitude=request_payload.location.longitude,
        )
    else:
        form = await request.form()
        body_hash = await get_multipart_hash(dict(form))
        if idempotency_key:
            replay = get_replayed_response(str(current.user.id), idempotency_key, body_hash)
            if replay:
                return success_response(replay)
        content = form.get("content")
        created_at = form.get("created_at")
        latitude = form.get("latitude")
        longitude = form.get("longitude")
        image = form.get("image")
        if not content or not created_at:
            raise AppError("invalid_payload", "Missing content/created_at", 422)
        content_text = cast(str, content)
        created_at_text = cast(str, created_at)
        upload_id = None
        if isinstance(image, UploadFile):
            row = UploadService(db).upload_single(image, current.user.id)
            upload_id = str(row.id)
        post = service.create_post(
            user_id=current.user.id,
            content=content_text,
            created_at=datetime.fromisoformat(created_at_text),
            upload_id=upload_id,
            latitude=float(cast(str, latitude)) if latitude is not None else None,
            longitude=float(cast(str, longitude)) if longitude is not None else None,
        )

    response_payload = service.post_payload(post)
    if idempotency_key:
        save_response(str(current.user.id), idempotency_key, body_hash, response_payload)
    return success_response(response_payload, status_code=201)


@router.get("/posts")
def list_posts(
    cursor: str | None = None,
    limit: int = DEFAULT_POST_LIMIT,
    user_id: uuid.UUID | None = None,
    near: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    del current
    near_parsed = None
    if near:
        lat, lng, radius = near.split(",")
        near_parsed = (float(lat), float(lng), float(radius))
    lim = min(max(limit, 1), MAX_POST_LIMIT)
    rows = service.repo.list_posts(cursor, lim, user_id, near_parsed)
    payload = [service.post_payload(x) for x in rows]
    next_cursor = None
    if rows:
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
    return success_response(payload, meta={"cursor": cursor, "next_cursor": next_cursor, "limit": lim})


@router.get("/posts/{post_id}")
def get_post(
    post_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    del current
    post = service.repo.get_post(post_id)
    from app.common.errors.exceptions import AppError

    if not post:
        raise AppError("not_found", "Post not found", 404)
    return success_response(service.post_payload(post))


@router.patch("/posts/{post_id}", dependencies=[WriteRateLimit])
def patch_post(
    post_id: uuid.UUID,
    payload: SocialPatchRequest,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    post = service.patch_post(post_id, current.user.id, payload.content)
    return success_response(service.post_payload(post))


@router.delete("/posts/{post_id}", dependencies=[WriteRateLimit])
def delete_post(
    post_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    service.delete_post(post_id, current.user.id)
    return success_response({"deleted": True})


@router.post("/posts/{post_id}/likes", dependencies=[WriteRateLimit])
def like_post(
    post_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    service.add_like(post_id, current.user.id)
    return success_response({"liked": True})


@router.delete("/posts/{post_id}/likes", dependencies=[WriteRateLimit])
def unlike_post(
    post_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    service.remove_like(post_id, current.user.id)
    return success_response({"liked": False})


@router.get("/posts/{post_id}/likes")
def list_likes(
    post_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del current
    repo = SocialRepository(db)
    rows = repo.likes(post_id)
    return success_response(
        [{"id": str(x.id), "user_id": str(x.user_id), "created_at": x.created_at} for x in rows]
    )


@router.post("/posts/{post_id}/comments", dependencies=[WriteRateLimit])
def create_comment(
    post_id: uuid.UUID,
    payload: CommentCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    row = service.add_comment(post_id, current.user.id, payload.content)
    return success_response(
        {
            "id": str(row.id),
            "author_id": str(row.user_id),
            "post_id": str(row.post_id),
            "content": row.content,
            "created_at": row.created_at,
        },
        status_code=201,
    )


@router.get("/posts/{post_id}/comments")
def list_comments(
    post_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    del current
    rows = service.repo.list_comments(post_id)
    return success_response(
        [
            {
                "id": str(x.id),
                "author_id": str(x.user_id),
                "post_id": str(x.post_id),
                "content": x.content,
                "created_at": x.created_at,
            }
            for x in rows
        ]
    )


@router.delete("/comments/{comment_id}", dependencies=[WriteRateLimit])
def delete_comment(
    comment_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    service.delete_comment(comment_id, current.user.id)
    return success_response({"deleted": True})
