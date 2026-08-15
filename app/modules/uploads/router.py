import uuid

from fastapi import APIRouter, Depends, File, UploadFile

from app.common.rate_limit.dependencies import WriteRateLimit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.uploads.dependencies import get_upload_service
from app.modules.uploads.schemas import UploadedAssetResponse
from app.modules.uploads.service import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/images", dependencies=[WriteRateLimit])
def upload_image_single(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(get_current_user),
    service: UploadService = Depends(get_upload_service),
):
    row = service.upload_single(file, current.user.id)
    return success_response(UploadedAssetResponse.model_validate(row).model_dump(mode="json"), status_code=201)


@router.post("/images/batch", dependencies=[WriteRateLimit])
def upload_image_batch(
    files: list[UploadFile] = File(...),
    current: CurrentUser = Depends(get_current_user),
    service: UploadService = Depends(get_upload_service),
):
    rows = [service.upload_single(f, current.user.id) for f in files]
    return success_response(
        [UploadedAssetResponse.model_validate(x).model_dump(mode="json") for x in rows],
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
