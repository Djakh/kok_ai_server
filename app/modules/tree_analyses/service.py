from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.config import Settings
from app.common.errors.exceptions import AppError
from app.common.observability import analysis_concurrency_slot, increment, request_id_context
from app.common.storage.s3 import put_private_image
from app.modules.tree_analyses.images import PreparedImage
from app.modules.tree_analyses.models import (
    IdempotencyRecord,
    TreeAnalysis,
    TreeAnalysisCandidate,
    TreeAnalysisImage,
)
from app.modules.tree_analyses.provider import (
    PlantAnalysisProvider,
    ProviderError,
    ProviderImage,
)
from app.modules.tree_analyses.repository import TreeAnalysisRepository
from app.modules.users.models import UserSettings

StorageWriter = Callable[[bytes, str, str, str], str]
IDEMPOTENCY_CONSTRAINT = "uq_tree_analyses_owner_idempotency"
logger = logging.getLogger(__name__)
MAX_PROVIDER_CUSTOM_ID = (1 << 53) - 1


def new_provider_custom_id() -> int:
    """Return a positive numeric ID safe across environments and JSON implementations."""
    return secrets.randbelow(MAX_PROVIDER_CUSTOM_ID) + 1


def integrity_constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def request_fingerprint(
    images: list[PreparedImage], photo_types: list[str], location_evidence: dict[str, Any]
) -> str:
    canonical = {
        "checksums": [image.checksum for image in images],
        "photo_types": photo_types,
        "location_evidence": location_evidence,
    }
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def candidate_payload(row: TreeAnalysisCandidate) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "common_name": row.common_name,
        "scientific_name": row.scientific_name,
        "confidence": row.confidence,
        "genus": row.genus,
        "family": row.family,
        "description": row.description,
        "representative_image_url": row.representative_image_url,
        "image_source_url": row.image_source_url,
    }


class TreeAnalysisService:
    def __init__(
        self,
        db: Session,
        provider: PlantAnalysisProvider,
        settings: Settings,
        storage_writer: StorageWriter = put_private_image,
    ):
        self.db = db
        self.repo = TreeAnalysisRepository(db)
        self.provider = provider
        self.settings = settings
        self.storage_writer = storage_writer

    async def analyze(
        self,
        owner_id: uuid.UUID,
        images: list[PreparedImage],
        photo_types: list[str],
        location_evidence: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[TreeAnalysis, bool]:
        fingerprint = request_fingerprint(images, photo_types, location_evidence)
        idem = (
            self.db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.principal_id == owner_id,
                IdempotencyRecord.method == "POST",
                IdempotencyRecord.route == "/api/v1/tree-analyses",
                IdempotencyRecord.key == idempotency_key,
            )
            .with_for_update()
            .first()
        )
        if idem:
            if idem.request_hash != fingerprint:
                raise AppError(
                    "idempotency_conflict",
                    "Idempotency-Key was already used with a different request.",
                    409,
                )
            if idem.resource_id:
                replay_analysis = self.repo.get(idem.resource_id, owner_id)
                if idem.state == "completed" and replay_analysis:
                    return replay_analysis, True
                if replay_analysis and replay_analysis.status == "no_plant_detected":
                    raise AppError(
                        "no_plant_detected",
                        "The submitted photos were not recognized as a plant.",
                        422,
                        {"analysis_id": str(replay_analysis.id)},
                    )
                if replay_analysis and idem.state == "failed_retryable":
                    code = replay_analysis.error_code or "ai_provider_unavailable"
                    status = 504 if code == "request_timeout" else 502
                    raise AppError(
                        code,
                        "The previous provider attempt did not complete; no duplicate call was made.",
                        status,
                        {"analysis_id": str(replay_analysis.id)},
                    )
            raise AppError("request_in_progress", "The matching analysis is still processing.", 409)
        existing = self.repo.get_by_idempotency(owner_id, idempotency_key)
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise AppError(
                    "idempotency_conflict",
                    "Idempotency-Key was already used with a different request.",
                    409,
                )
            if existing.status == "completed" and existing.normalized_result:
                return existing, True
            if existing.status in {"provider_pending", "images_stored", "validating", "received"}:
                raise AppError(
                    "request_in_progress",
                    "The matching analysis is still processing; retrieve it by id.",
                    409,
                    {"analysis_id": str(existing.id)},
                )
            raise AppError(
                existing.error_code or "ai_provider_unavailable",
                "The previous analysis attempt did not complete.",
                502,
                {"analysis_id": str(existing.id)},
            )

        try:
            analysis = self.repo.create(
                TreeAnalysis(
                    owner_user_id=owner_id,
                    status="validating",
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                    latitude=float(location_evidence["latitude"]),
                    longitude=float(location_evidence["longitude"]),
                    location_evidence=location_evidence,
                    provider_name="kindwise_plant_id",
                    health_mode=self.settings.kindwise_health_mode,
                    numeric_provider_custom_id=new_provider_custom_id(),
                )
            )
        except IntegrityError as exc:
            constraint_name = integrity_constraint_name(exc)
            self.db.rollback()
            if constraint_name != IDEMPOTENCY_CONSTRAINT:
                logger.error(
                    "unexpected_tree_analysis_integrity_error",
                    extra={
                        "request_id": request_id_context.get(),
                        "endpoint": "/api/v1/tree-analyses",
                        "path": "/api/v1/tree-analyses",
                        "principal_id": str(owner_id),
                        "constraint_name": constraint_name,
                        "error_type": type(exc.orig).__name__,
                    },
                )
                raise
            concurrent = self.repo.get_by_idempotency(owner_id, idempotency_key)
            if concurrent and concurrent.request_fingerprint == fingerprint:
                if concurrent.status == "completed" and concurrent.normalized_result:
                    return concurrent, True
                raise AppError(
                    "request_in_progress",
                    "The matching analysis is still processing.",
                    409,
                    {"analysis_id": str(concurrent.id)},
                ) from exc
            raise AppError(
                "idempotency_conflict",
                "Idempotency-Key was already used with a different request.",
                409,
            ) from exc
        idem = IdempotencyRecord(
            principal_id=owner_id,
            method="POST",
            route="/api/v1/tree-analyses",
            key=idempotency_key,
            request_hash=fingerprint,
            state="validating",
            resource_type="tree_analysis",
            resource_id=analysis.id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=self.settings.idempotency_ttl_hours),
        )
        self.db.add(idem)
        self.db.commit()

        try:
            for ordinal, (image, photo_type) in enumerate(zip(images, photo_types, strict=True)):
                original_object_key = await asyncio.to_thread(
                    self.storage_writer,
                    image.original_content,
                    str(owner_id),
                    image.content_type,
                    image.extension,
                )
                object_key = await asyncio.to_thread(
                    self.storage_writer,
                    image.content,
                    str(owner_id),
                    image.content_type,
                    image.extension,
                )
                self.repo.add_image(
                    TreeAnalysisImage(
                        analysis_id=analysis.id,
                        organ=photo_type,
                        ordinal=ordinal,
                        object_key=object_key,
                        original_object_key=original_object_key,
                        mime_type=image.content_type,
                        byte_size=len(image.content),
                        checksum=image.checksum,
                        original_filename=Path(image.original_filename).name[:255],
                    )
                )
            analysis.status = "provider_pending"
            idem.state = "provider_pending"
            self.db.commit()

            provider_images = [
                ProviderImage(
                    image.content, image.content_type, f"image-{index + 1}.{image.extension}"
                )
                for index, image in enumerate(images)
            ]
            increment("kok_ai_analysis_total", {"outcome": "started"})
            try:
                settings_row = (
                    self.db.query(UserSettings).filter(UserSettings.user_id == owner_id).first()
                )
                user_language = settings_row.language_code if settings_row else "en"
                if user_language not in {"en", "ru", "uz"}:
                    user_language = "en"
                async with analysis_concurrency_slot():
                    result = await self.provider.analyze(
                        provider_images,
                        photo_types,
                        {
                            "custom_id": analysis.numeric_provider_custom_id,
                            "location_evidence": location_evidence,
                            "language": user_language,
                        },
                    )
            except ProviderError as exc:
                if exc.code != "request_timeout":
                    raise
                recovered = await self.provider.retrieve(analysis.numeric_provider_custom_id)
                if recovered is None:
                    raise
                result = recovered

            analyzed_at = datetime.now(timezone.utc)
            analysis.provider_is_plant_binary = result.is_plant
            analysis.provider_is_plant_probability = result.is_plant_probability
            analysis.provider_metadata = {
                "model_version": result.provider_metadata.get("model_version")
            }
            analysis.raw_provider_response = None
            analysis.analyzed_at = analyzed_at
            if not result.is_plant:
                analysis.status = "no_plant_detected"
                analysis.error_code = "no_plant_detected"
                idem.state = "failed_terminal"
                idem.response_status = 422
                self.db.commit()
                raise AppError(
                    "no_plant_detected",
                    "The submitted photos were not recognized as a plant.",
                    422,
                    {"analysis_id": str(analysis.id)},
                )

            rows: list[TreeAnalysisCandidate] = []
            for ordinal, item in enumerate(result.species_candidates[:5]):
                row = self.repo.add_candidate(
                    TreeAnalysisCandidate(
                        analysis_id=analysis.id,
                        provider_taxon_id=item.provider_taxon_id,
                        scientific_name=item.scientific_name,
                        common_name=item.common_names[0] if item.common_names else None,
                        confidence=item.confidence,
                        genus=item.genus,
                        family=item.family,
                        description=item.description,
                        representative_image_url=item.representative_image_url,
                        image_source_url=item.image_source_url,
                        attribution_metadata=item.metadata,
                        ordinal=ordinal,
                    )
                )
                rows.append(row)
            normalized = {
                "id": str(analysis.id),
                "provider": "kindwise_plant_id",
                "analyzed_at": analyzed_at.isoformat().replace("+00:00", "Z"),
                "candidates": [candidate_payload(row) for row in rows],
                "species_candidates": [candidate_payload(row) for row in rows],
                "health": result.health
                or {"status": "not_available", "confidence": None, "summary": None},
                "capabilities": {
                    "identification": "available",
                    "health": "available" if result.health else "not_available",
                },
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
            analysis.status = "completed"
            analysis.normalized_result = normalized
            idem.state = "completed"
            idem.response_status = 201
            idem.response_body = normalized
            self.db.commit()
            self.db.refresh(analysis)
            increment("kok_ai_analysis_total", {"outcome": "completed"})
            return analysis, False
        except AppError:
            if analysis.status != "no_plant_detected":
                analysis.status = "failed_terminal"
                idem.state = "failed_terminal"
                self.db.commit()
            raise
        except ProviderError as exc:
            analysis.status = "failed_retryable" if exc.status_code >= 500 else "failed_terminal"
            analysis.error_code = exc.code
            idem.state = analysis.status
            self.db.commit()
            increment("kok_ai_analysis_total", {"outcome": "failed", "code": exc.code})
            raise AppError(exc.code, exc.message, exc.status_code, exc.details) from exc
        except Exception as exc:
            analysis.status = "failed_retryable"
            analysis.error_code = "backend_unavailable"
            idem.state = "failed_retryable"
            self.db.commit()
            raise AppError("backend_unavailable", "Image storage is unavailable.", 503) from exc

    def get(self, analysis_id: uuid.UUID, owner_id: uuid.UUID) -> TreeAnalysis:
        analysis = self.repo.get(analysis_id, owner_id)
        if not analysis:
            raise AppError("analysis_not_found", "Tree analysis not found.", 404)
        return analysis

    def get_completed(self, analysis_id: uuid.UUID, owner_id: uuid.UUID) -> TreeAnalysis:
        analysis = self.get(analysis_id, owner_id)
        if analysis.status != "completed" or not analysis.normalized_result:
            raise AppError("analysis_not_completed", "Tree analysis is not completed.", 409)
        return analysis
