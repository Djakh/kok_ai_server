import uuid
from datetime import datetime
from typing import Any, Literal, cast

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
from app.common.storage.s3 import get_public_asset_url
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
from app.modules.users.models import User

router = APIRouter(prefix="/social", tags=["social"])


def _set_viewer(service: SocialService, user_id: uuid.UUID) -> None:
    service.viewer_id = user_id
    service.repo.viewer_id = user_id


def _comment_payload(service: SocialService, row) -> dict:  # noqa: ANN001
    if hasattr(service, "comment_payload"):
        return service.comment_payload(row)
    return {
        "id": str(row.id),
        "author_id": str(row.user_id),
        "author": {
            "id": str(row.user_id),
            "username": "unknown",
            "full_name": None,
            "avatar_url": None,
        },
        "post_id": str(row.post_id),
        "content": row.content,
        "created_at": row.created_at,
        "updated_at": getattr(row, "updated_at", row.created_at),
        "like_count": 0,
        "liked_by_me": False,
        "is_mine": service.viewer_id == row.user_id,
    }


def _parse_near(near: str | None) -> tuple[float, float, float] | None:
    if not near:
        return None
    try:
        lat, lng, radius = (float(value) for value in near.split(","))
    except ValueError as exc:
        raise AppError(
            "invalid_near",
            "near must be latitude,longitude,radius_meters",
            422,
        ) from exc
    if not -90 <= lat <= 90 or not -180 <= lng <= 180 or not 1 <= radius <= 50_000:
        raise AppError("invalid_near", "near coordinates or radius are outside limits", 422)
    return lat, lng, radius


def _post_page(
    service: SocialService,
    *,
    cursor: str | None,
    limit: int,
    author_id: uuid.UUID | None = None,
    near: str | None = None,
    following_only: bool = False,
) -> tuple[list[dict], str | None, int]:
    lim = min(max(limit, 1), MAX_POST_LIMIT)
    if following_only:
        rows = service.repo.list_posts(
            cursor,
            lim + 1,
            author_id,
            _parse_near(near),
            following_only=True,
        )
    else:
        rows = service.repo.list_posts(cursor, lim + 1, author_id, _parse_near(near))
    has_more = len(rows) > lim
    page = rows[:lim]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
    return [service.post_payload(row) for row in page], next_cursor, lim


def _timeline_response(
    service: SocialService,
    *,
    cursor: str | None,
    limit: int,
    author_id: uuid.UUID | None = None,
    near: str | None = None,
    following_only: bool = False,
    include_total: bool = False,
    author: Any | None = None,
):
    items, next_cursor, lim = _post_page(
        service,
        cursor=cursor,
        limit=limit,
        author_id=author_id,
        near=near,
        following_only=following_only,
    )
    data: dict = {"items": items, "next_cursor": next_cursor}
    if include_total and author_id:
        data["total_count"] = service.repo.count_posts(author_id)
    if author is not None:
        avatar_asset_id = getattr(author, "avatar_asset_id", None)
        data["author"] = {
            "id": str(author.id),
            "username": author.username,
            "full_name": getattr(author, "full_name", None),
            "avatar_url": (
                get_public_asset_url(avatar_asset_id) if avatar_asset_id else None
            ),
        }
    return success_response(
        data,
        meta={"cursor": cursor, "next_cursor": next_cursor, "limit": lim},
    )


@router.post("/posts", dependencies=[WriteRateLimit])
async def create_post(
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: SocialService = Depends(get_social_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _set_viewer(service, current.user.id)
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
            row = UploadService(db).upload_single(image, current.user.id, "social_post")
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
    _set_viewer(service, current.user.id)
    return _timeline_response(
        service,
        cursor=cursor,
        limit=limit,
        author_id=user_id,
        near=near,
    )


@router.get("/feed")
def get_feed(
    scope: Literal["all", "following"] = "all",
    cursor: str | None = None,
    limit: int = DEFAULT_POST_LIMIT,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    """Return the discovery feed or posts from followed authors plus the viewer."""
    _set_viewer(service, current.user.id)
    return _timeline_response(
        service,
        cursor=cursor,
        limit=limit,
        following_only=scope == "following",
    )


@router.get("/posts/me")
@router.get("/my-posts", include_in_schema=False)
def my_posts(
    cursor: str | None = None,
    limit: int = DEFAULT_POST_LIMIT,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    _set_viewer(service, current.user.id)
    return _timeline_response(
        service,
        cursor=cursor,
        limit=limit,
        author_id=current.user.id,
        include_total=True,
        author=current.user,
    )


@router.get("/authors/{author_id}/posts")
@router.get("/author-posts/{author_id}", include_in_schema=False)
def author_posts(
    author_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = DEFAULT_POST_LIMIT,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    _set_viewer(service, current.user.id)
    author = service.db.query(User).filter(User.id == author_id, User.is_active.is_(True)).first()
    if not author:
        raise AppError("not_found", "Author not found", 404)
    return _timeline_response(
        service,
        cursor=cursor,
        limit=limit,
        author_id=author_id,
        include_total=True,
        author=author,
    )


@router.get("/posts/{post_id}")
def get_post(
    post_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    _set_viewer(service, current.user.id)
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
    _set_viewer(service, current.user.id)
    post = service.patch_post(
        post_id,
        current.user.id,
        payload.content,
        payload.remove_image,
    )
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
    cursor: str | None = None,
    limit: int = 50,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = SocialRepository(db)
    repo.viewer_id = current.user.id
    if not repo.get_post(post_id):
        raise AppError("not_found", "Post not found", 404)
    lim = min(max(limit, 1), 100)
    rows = repo.likes(post_id, cursor, lim + 1)
    has_more = len(rows) > lim
    page = rows[:lim]
    items = []
    for like in page:
        user = db.query(User).filter(User.id == like.user_id).first()
        avatar_asset_id = user.avatar_asset_id if user else None
        items.append(
            {
                "id": str(like.id),
                "user_id": str(like.user_id),
                "user": {
                    "id": str(like.user_id),
                    "username": user.username if user else "unknown",
                    "full_name": user.full_name if user else None,
                    "avatar_url": (
                        get_public_asset_url(avatar_asset_id) if avatar_asset_id else None
                    ),
                },
                "created_at": like.created_at,
            }
        )
    next_cursor = None
    if has_more and page:
        next_cursor = encode_cursor(page[-1].created_at, str(page[-1].id))
    return success_response(
        {"items": items, "next_cursor": next_cursor},
        meta={"cursor": cursor, "next_cursor": next_cursor, "limit": lim},
    )


@router.post("/posts/{post_id}/comments", dependencies=[WriteRateLimit])
def create_comment(
    post_id: uuid.UUID,
    payload: CommentCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    _set_viewer(service, current.user.id)
    row = service.add_comment(post_id, current.user.id, payload.content)
    return success_response(_comment_payload(service, row), status_code=201)


@router.get("/posts/{post_id}/comments")
def list_comments(
    post_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 50,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    _set_viewer(service, current.user.id)
    if not service.repo.get_post(post_id):
        raise AppError("not_found", "Post not found", 404)
    lim = min(max(limit, 1), 100)
    rows = service.repo.list_comments(post_id, cursor, lim + 1)
    has_more = len(rows) > lim
    page = rows[:lim]
    next_cursor = None
    if has_more and page:
        next_cursor = encode_cursor(page[-1].created_at, str(page[-1].id))
    return success_response(
        {
            "items": [_comment_payload(service, row) for row in page],
            "next_cursor": next_cursor,
        },
        meta={"cursor": cursor, "next_cursor": next_cursor, "limit": lim},
    )


@router.delete("/posts/{post_id}/comments/{comment_id}", dependencies=[WriteRateLimit])
@router.delete("/comments/{comment_id}", dependencies=[WriteRateLimit], include_in_schema=False)
def delete_comment(
    comment_id: uuid.UUID,
    post_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    service: SocialService = Depends(get_social_service),
):
    if post_id:
        row = service.repo.get_comment(comment_id)
        if not row or row.post_id != post_id:
            raise AppError("not_found", "Comment not found", 404)
    service.delete_comment(comment_id, current.user.id)
    return success_response({"deleted": True})
