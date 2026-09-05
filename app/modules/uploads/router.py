import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.common.rate_limit.dependencies import WriteRateLimit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.uploads.dependencies import get_upload_service
from app.modules.uploads.schemas import UploadedAssetResponse
from app.modules.uploads.service import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", dependencies=[WriteRateLimit], include_in_schema=True)
@router.post("/images", dependencies=[WriteRateLimit], include_in_schema=False)
def upload_image_single(
    file: UploadFile = File(...),
    purpose: Annotated[
        Literal["general", "avatar", "social_post", "tree_issue"], Form()
    ] = "general",
    current: CurrentUser = Depends(get_current_user),
    service: UploadService = Depends(get_upload_service),
):
    row = service.upload_single(file, current.user.id, purpose)
    return success_response(
        UploadedAssetResponse.model_validate(row).model_dump(mode="json"), status_code=201
    )


@router.post("/batch", dependencies=[WriteRateLimit], include_in_schema=True)
@router.post("/images/batch", dependencies=[WriteRateLimit], include_in_schema=False)
def upload_image_batch(
    files: Annotated[list[UploadFile], File(min_length=1, max_length=5)],
    purpose: Annotated[
        Literal["general", "avatar", "social_post", "tree_issue"], Form()
    ] = "general",
    current: CurrentUser = Depends(get_current_user),
    service: UploadService = Depends(get_upload_service),
):
    rows = [service.upload_single(f, current.user.id, purpose) for f in files]
    items = [UploadedAssetResponse.model_validate(x).model_dump(mode="json") for x in rows]
    return success_response(
        {"items": items, "next_cursor": None},
        status_code=201,
    )


@router.get("/{upload_id}")
def get_upload(
    upload_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: UploadService = Depends(get_upload_service),
):
    row = service.get_owned(upload_id, current.user.id)
    return success_response(UploadedAssetResponse.model_validate(row).model_dump(mode="json"))
