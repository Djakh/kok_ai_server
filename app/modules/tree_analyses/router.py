import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

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


def mobile_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    candidates = result.get("species_candidates") or result.get("candidates") or []
    result["candidates"] = candidates
    result["species_candidates"] = candidates
    health = result.get("health")
    if not health:
        health = {"status": "not_available", "confidence": None, "summary": None}
    result["health"] = health
    result.setdefault(
        "capabilities",
        {
            "identification": "available",
            "health": "not_available" if health["status"] == "not_available" else "available",
        },
    )
    result.setdefault(
        "attribution",
        {"provider": "Kindwise Plant.id", "provider_id": "kindwise_plant_id"},
    )
    result.setdefault(
        "uncertainty",
        {
            "confidence_scale": "0_to_1",
            "candidate_order": "descending_probability",
            "user_confirmation_required": True,
        },
    )
    return result


def _mobile_location_evidence(
    location_evidence: str | None,
    latitude: float | None,
    longitude: float | None,
    accuracy_meters: float | None,
    captured_at: datetime | None,
) -> LocationEvidence:
    if location_evidence:
        try:
            return LocationEvidence.model_validate(json.loads(location_evidence))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AppError(
                "invalid_location_evidence", "Location evidence is invalid.", 422
            ) from exc
    if latitude is None or longitude is None:
        raise AppError(
            "invalid_location_evidence",
            "Send location_evidence or both latitude and longitude.",
            422,
        )
    accuracy = accuracy_meters or 1.0
    return LocationEvidence(
        latitude=latitude,
        longitude=longitude,
        horizontal_accuracy_meters=accuracy,
        accepted_sample_count=3,
        rejected_sample_count=0,
        capture_duration_ms=1,
        best_sample_accuracy_meters=accuracy,
        captured_at=captured_at or datetime.now(timezone.utc),
        quality="poor" if accuracy_meters is None else "acceptable",
    )


@router.post(
    "",
    response_model=AnalysisEnvelope,
    status_code=201,
    dependencies=[AnalysisRateLimit],
    summary="Analyze categorized tree photos using server-side Kindwise Plant.id",
)
async def create_tree_analysis(
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
    photos: Annotated[
        list[UploadFile] | None, File(description="2-5 repeated JPEG/PNG photos")
    ] = None,
    photo_types: Annotated[
        list[str] | None, Form(description="One category for each photo")
    ] = None,
    location_evidence: Annotated[
        str | None, Form(description="JSON LocationEvidence object")
    ] = None,
    images: Annotated[list[UploadFile] | None, File(description="Mobile alias for photos")] = None,
    organs: Annotated[list[str] | None, Form(description="Mobile alias for photo_types")] = None,
    latitude: Annotated[float | None, Form()] = None,
    longitude: Annotated[float | None, Form()] = None,
    accuracy_meters: Annotated[float | None, Form(gt=0)] = None,
    captured_at: Annotated[datetime | None, Form()] = None,
    current: CurrentUser = Depends(get_current_user),
    service: TreeAnalysisService = Depends(get_tree_analysis_service),
):
    submitted_images = photos or images or []
    submitted_types = photo_types or organs or []
    if photos and images:
        raise AppError("validation_error", "Send photos or images, not both.", 422)
    if photo_types and organs:
        raise AppError("validation_error", "Send photo_types or organs, not both.", 422)
    normalized_aliases = [
        "whole_tree" if value.strip().lower() == "auto" else value for value in submitted_types
    ]
    evidence = _mobile_location_evidence(
        location_evidence, latitude, longitude, accuracy_meters, captured_at
    )
    normalized_types = validate_photo_types(normalized_aliases, len(submitted_images))
    prepared = await prepare_images(submitted_images, get_settings(), minimum=2)
    analysis, replayed = await service.analyze(
        current.user.id,
        prepared,
        normalized_types,
        evidence.model_dump(mode="json"),
        idempotency_key,
    )
    return success_response(
        mobile_analysis_payload(analysis.normalized_result or {}),
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
        return success_response(mobile_analysis_payload(analysis.normalized_result))
    return success_response(
        {
            "id": str(analysis.id),
            "status": analysis.status,
            "provider": analysis.provider_name,
            "analyzed_at": analysis.analyzed_at,
            "candidates": [],
            "species_candidates": [],
            "health": {"status": "not_available", "confidence": None, "summary": None},
            "capabilities": {"identification": "pending", "health": "not_available"},
            "attribution": {
                "provider": "Kindwise Plant.id",
                "provider_id": "kindwise_plant_id",
            },
            "uncertainty": {
                "confidence_scale": "0_to_1",
                "candidate_order": "descending_probability",
                "user_confirmation_required": True,
            },
        }
    )
