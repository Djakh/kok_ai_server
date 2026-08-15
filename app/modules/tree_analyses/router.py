import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import ValidationError

from app.common.config import get_settings
from app.common.errors.exceptions import AppError
from app.common.rate_limit.dependencies import AnalysisRateLimit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.tree_analyses.dependencies import get_tree_analysis_service
from app.modules.tree_analyses.images import prepare_images, validate_photo_types
from app.modules.tree_analyses.schemas import AnalysisEnvelope, LocationEvidence
from app.modules.tree_analyses.service import TreeAnalysisService

router = APIRouter(prefix="/tree-analyses", tags=["tree analyses"])


@router.post(
    "",
    response_model=AnalysisEnvelope,
    status_code=201,
    dependencies=[AnalysisRateLimit],
    summary="Analyze categorized tree photos using server-side Kindwise Plant.id",
)
async def create_tree_analysis(
    photos: Annotated[list[UploadFile], File(description="2-5 repeated JPEG/PNG photos")],
    photo_types: Annotated[list[str], Form(description="One category for each photo")],
    location_evidence: Annotated[str, Form(description="JSON LocationEvidence object")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
    current: CurrentUser = Depends(get_current_user),
    service: TreeAnalysisService = Depends(get_tree_analysis_service),
):
    try:
        evidence = LocationEvidence.model_validate(json.loads(location_evidence))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AppError("invalid_location_evidence", "Location evidence is invalid.", 422) from exc
    normalized_types = validate_photo_types(photo_types, len(photos))
    prepared = await prepare_images(photos, get_settings(), minimum=2)
    analysis, replayed = await service.analyze(
        current.user.id,
        prepared,
        normalized_types,
        evidence.model_dump(mode="json"),
        idempotency_key,
    )
    return success_response(
        analysis.normalized_result,
        meta={"idempotency_replayed": True} if replayed else None,
        status_code=200 if replayed else 201,
    )


@router.get("/{analysis_id}")
def get_tree_analysis(
    analysis_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: TreeAnalysisService = Depends(get_tree_analysis_service),
):
    analysis = service.get(analysis_id, current.user.id)
    if analysis.status == "completed" and analysis.normalized_result:
        return success_response(analysis.normalized_result)
    return success_response(
        {
            "id": str(analysis.id),
            "status": analysis.status,
            "provider": analysis.provider_name,
            "analyzed_at": analysis.analyzed_at,
            "candidates": [],
            "health": None,
        }
    )
