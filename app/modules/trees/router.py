import json
import math
import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.common.config import get_settings
from app.common.db.session import get_db
from app.common.errors.exceptions import AppError
from app.common.idempotency.service import (
    get_body_hash,
    get_multipart_hash,
    get_replayed_response,
    save_response,
)
from app.common.pagination.cursor import encode_cursor
from app.common.rate_limit.dependencies import AnalysisRateLimit, WriteRateLimit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user, require_roles
from app.modules.social.models import SocialPost
from app.modules.tree_analyses.dependencies import get_tree_analysis_service
from app.modules.tree_analyses.images import prepare_images, validate_photo_types
from app.modules.tree_analyses.schemas import LocationEvidence
from app.modules.tree_analyses.service import TreeAnalysisService
from app.modules.trees.constants import DEFAULT_TREE_LIMIT, MAX_TREE_LIMIT
from app.modules.trees.dependencies import get_tree_service
from app.modules.trees.schemas import (
    TreeCreateFromAnalysisRequest,
    TreePatchRequest,
    TreeRegisterRequest,
    TreeVerifyRequest,
)
from app.modules.trees.service import TreeService
from app.modules.uploads.service import UploadService

router = APIRouter(prefix="/trees", tags=["trees"])


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@router.post("/register", dependencies=[WriteRateLimit])
async def register_tree(
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: TreeService = Depends(get_tree_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body_hash = await get_body_hash(request)
        if idempotency_key:
            replay = get_replayed_response(str(current.user.id), idempotency_key, body_hash)
            if replay:
                return success_response(replay)
        request_payload = TreeRegisterRequest.model_validate(await request.json())
        image_ids = request_payload.images.model_dump()
        tree = service.register_tree(
            owner_id=current.user.id,
            name=request_payload.name,
            captured_at=request_payload.captured_at,
            lat=request_payload.location.latitude,
            lng=request_payload.location.longitude,
            accuracy_meters=request_payload.location.accuracy_meters,
            image_asset_ids=image_ids,
        )
    else:
        form = await request.form()
        body_hash = await get_multipart_hash(dict(form))
        if idempotency_key:
            replay = get_replayed_response(str(current.user.id), idempotency_key, body_hash)
            if replay:
                return success_response(replay)
        name = form.get("name")
        latitude = form.get("latitude")
        longitude = form.get("longitude")
        accuracy_meters = form.get("accuracy_meters")
        captured_at = form.get("captured_at")
        front = form.get("front")
        trunk = form.get("trunk")
        leaves = form.get("leaves")
        if not all([name, latitude, longitude, accuracy_meters, captured_at, front, trunk, leaves]):
            raise AppError("invalid_payload", "Missing multipart fields", 422)
        if not all(isinstance(file, StarletteUploadFile) for file in (front, trunk, leaves)):
            raise AppError("invalid_payload", "Tree images must be uploaded files", 422)
        upload_service = UploadService(db)
        a_front = upload_service.upload_single(cast(StarletteUploadFile, front), current.user.id)
        a_trunk = upload_service.upload_single(cast(StarletteUploadFile, trunk), current.user.id)
        a_leaves = upload_service.upload_single(cast(StarletteUploadFile, leaves), current.user.id)
        tree = service.register_tree(
            owner_id=current.user.id,
            name=cast(str, name),
            captured_at=datetime.fromisoformat(cast(str, captured_at)),
            lat=float(cast(str, latitude)),
            lng=float(cast(str, longitude)),
            accuracy_meters=float(cast(str, accuracy_meters)),
            image_asset_ids={
                "front": str(a_front.id),
                "trunk": str(a_trunk.id),
                "leaves": str(a_leaves.id),
            },
        )

    response_payload = service.tree_to_payload(tree)
    if idempotency_key:
        save_response(str(current.user.id), idempotency_key, body_hash, response_payload)
    return success_response(response_payload, status_code=201)


@router.get("/map")
def trees_map(
    bbox: str | None = None,
    center: str | None = None,
    radius: float | None = None,
    status: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    del current
    if bbox:
        min_lng, min_lat, max_lng, max_lat = [float(x) for x in bbox.split(",")]
        rows = service.repo.map_bbox(min_lng, min_lat, max_lng, max_lat, status)
    elif center and radius:
        lat, lng = [float(x) for x in center.split(",")]
        rows = service.repo.map_center_radius(lat, lng, radius, status)
    else:
        from app.common.errors.exceptions import AppError

        raise AppError("invalid_query", "Provide bbox or center+radius", 422)
    return success_response([service.tree_to_payload(x) for x in rows])


@router.post("", dependencies=[WriteRateLimit])
async def create_tree_from_analysis(
    request: Request,
    payload: TreeCreateFromAnalysisRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=160),
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    body_hash = await get_body_hash(request)
    replay = service.idempotency_replay(
        current.user.id, "/api/v1/trees", idempotency_key, body_hash
    )
    if replay:
        return success_response(replay)
    record = service.idempotency_begin(
        current.user.id, "/api/v1/trees", idempotency_key, body_hash
    )
    tree = service.create_from_analysis(
        current.user.id,
        payload.analysis_id,
        payload.selected_candidate_id,
        payload.manual_scientific_name,
        payload.location_evidence.model_dump(mode="json"),
        payload.duplicate_check_status,
        payload.nickname,
        payload.notes,
        payload.visibility,
    )
    response_payload = service.tree_to_payload(tree)
    service.idempotency_complete(record, tree.id, response_payload)
    return success_response(response_payload, status_code=201)


@router.get("/nearby")
def nearby_trees(
    latitude: float,
    longitude: float,
    radius_meters: float = 20,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    if not all(math.isfinite(value) for value in (latitude, longitude, radius_meters)):
        raise AppError("validation_error", "Nearby coordinates must be finite.", 400)
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or not 0 < radius_meters <= 100:
        raise AppError("validation_error", "Nearby query values are out of range.", 400)
    rows = service.repo.nearby(latitude, longitude, radius_meters, current.user.id)
    items = []
    for row in rows:
        tree = service.repo.get_tree(row.id)
        if tree is None:
            continue
        detail = service.tree_to_payload(tree)
        items.append(
            {
                "tree_id": str(tree.id),
                "display_name": tree.name,
                "scientific_name": detail["identification"]["scientific_name"],
                "image_url": detail["primary_image_url"],
                "distance_meters": round(float(row.distance_meters), 1),
                "horizontal_accuracy_meters": detail["location"]["horizontal_accuracy_meters"],
                "registered_at": tree.created_at,
            }
        )
    return success_response({"items": items})


@router.get("")
def list_trees(
    cursor: str | None = None,
    limit: int = DEFAULT_TREE_LIMIT,
    sort: Literal["newest", "nearest", "last_scanned"] = "newest",
    status: Literal["pending", "verified", "rejected"] | None = None,
    owner_id: str | None = None,
    q: str | None = None,
    species: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    normalized_cursor = _blank_to_none(cursor)
    normalized_status = _blank_to_none(status)
    normalized_q = _blank_to_none(q)
    normalized_owner_id = _blank_to_none(owner_id)
    parsed_owner_id: uuid.UUID | None = None
    if normalized_owner_id:
        try:
            parsed_owner_id = uuid.UUID(normalized_owner_id)
        except ValueError as exc:
            raise AppError("invalid_owner_id", "owner_id must be a valid UUID", 422) from exc

    lim = min(max(limit, 1), MAX_TREE_LIMIT)
    if sort == "nearest" and (latitude is None or longitude is None):
        raise AppError(
            "unsupported_sort_parameters",
            "latitude and longitude are required for nearest sort.",
            400,
        )
    if sort == "nearest":
        near_latitude = cast(float, latitude)
        near_longitude = cast(float, longitude)
        if (
            not math.isfinite(near_latitude)
            or not math.isfinite(near_longitude)
            or not -90 <= near_latitude <= 90
            or not -180 <= near_longitude <= 180
        ):
            raise AppError("unsupported_sort_parameters", "Nearest coordinates are invalid.", 400)
    rows = service.repo.list_trees(
        normalized_cursor,
        lim,
        normalized_status,
        parsed_owner_id,
        normalized_q,
        sort,
        current.user.id,
        species,
        latitude,
        longitude,
    )
    payload = [service.tree_to_summary(x) for x in rows]
    next_cursor = None
    if rows:
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
    return success_response(
        {"items": payload, "next_cursor": next_cursor, "has_more": len(rows) == lim}
    )


@router.post("/{tree_id}/scans", dependencies=[AnalysisRateLimit])
async def create_tree_scan(
    tree_id: uuid.UUID,
    photos: Annotated[list[UploadFile], File()],
    photo_types: Annotated[list[str], Form()],
    location_evidence: Annotated[str | None, Form()] = None,
    run_analysis: Annotated[bool, Form()] = True,
    captured_at: Annotated[datetime | None, Form()] = None,
    notes: Annotated[str | None, Form(max_length=2000)] = None,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)] = "",
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
    analysis_service: TreeAnalysisService = Depends(get_tree_analysis_service),
):
    tree = service.repo.get_tree(tree_id)
    if not tree:
        raise AppError("TREE_NOT_FOUND", "Tree not found.", 404)
    if tree.owner_user_id != current.user.id:
        raise AppError("FORBIDDEN", "Not tree owner.", 403)
    if not run_analysis:
        raise AppError("validation_error", "run_analysis=false is not supported for photo scans.", 422)
    if not idempotency_key:
        raise AppError("validation_error", "Idempotency-Key is required.", 422)
    if location_evidence:
        try:
            evidence = LocationEvidence.model_validate(json.loads(location_evidence))
        except Exception as exc:
            raise AppError("invalid_location_evidence", "Location evidence is invalid.", 422) from exc
    else:
        latitude, longitude = service._read_lat_lng(tree_id)
        now = datetime.now().astimezone()
        evidence = LocationEvidence(
            latitude=latitude,
            longitude=longitude,
            horizontal_accuracy_meters=1,
            accepted_sample_count=1,
            rejected_sample_count=0,
            capture_duration_ms=1,
            best_sample_accuracy_meters=1,
            captured_at=now,
            quality="poor",
        )
    prepared = await prepare_images(photos, get_settings(), minimum=2)
    normalized_types = validate_photo_types(photo_types, len(prepared))
    analysis, _ = await analysis_service.analyze(
        current.user.id,
        prepared,
        normalized_types,
        evidence.model_dump(mode="json"),
        idempotency_key,
    )
    scan = service.attach_scan(
        tree_id, current.user.id, analysis.id, captured_at, notes
    )
    return success_response(service.scan_to_payload(scan), status_code=201)


@router.get("/{tree_id}/scans")
def list_tree_scans(
    tree_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 20,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    tree = service.repo.get_tree(tree_id)
    if not tree:
        raise AppError("TREE_NOT_FOUND", "Tree not found.", 404)
    if tree.owner_user_id != current.user.id:
        raise AppError("FORBIDDEN", "Not tree owner.", 403)
    bounded_limit = min(max(limit, 1), 100)
    rows = service.repo.list_scans(tree_id, _blank_to_none(cursor), bounded_limit)
    return success_response({"items": [service.scan_to_payload(scan) for scan in rows]})


@router.get("/{tree_id}")
def tree_detail(
    tree_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    tree = service.ensure_readable(service.repo.get_tree(tree_id), current.user.id)
    return success_response(service.tree_to_payload(tree))


@router.patch("/{tree_id}")
def tree_patch(
    tree_id: uuid.UUID,
    payload: TreePatchRequest,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    tree = service.patch_tree(tree_id, current.user.id, payload.model_dump(exclude_none=True))
    return success_response(service.tree_to_payload(tree))


@router.get("/{tree_id}/timeline")
def tree_timeline(
    tree_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
):
    service.ensure_readable(service.repo.get_tree(tree_id), current.user.id)
    items = service.repo.list_events(tree_id)
    data = [
        {
            "id": str(x.id),
            "event_type": x.event_type.value,
            "details": x.details_json,
            "created_at": x.created_at,
        }
        for x in items
    ]
    return success_response(data)


@router.post("/{tree_id}/verify")
def tree_verify(
    tree_id: uuid.UUID,
    payload: TreeVerifyRequest,
    current: CurrentUser = Depends(require_roles({"moderator", "admin"})),
    service: TreeService = Depends(get_tree_service),
):
    tree = service.verify_tree(tree_id, current.user.id, payload.note)
    return success_response(service.tree_to_payload(tree))


@router.get("/{tree_id}/posts")
def tree_posts(
    tree_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: TreeService = Depends(get_tree_service),
    db: Session = Depends(get_db),
):
    service.ensure_readable(service.repo.get_tree(tree_id), current.user.id)
    items = (
        db.query(SocialPost)
        .filter(SocialPost.tree_id == tree_id, SocialPost.deleted_at.is_(None))
        .order_by(SocialPost.created_at.desc())
        .all()
    )
    data = [
        {
            "id": str(x.id),
            "content": x.content,
            "author_id": str(x.author_user_id),
            "created_at": x.created_at,
        }
        for x in items
    ]
    return success_response(data)
