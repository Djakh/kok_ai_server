import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db.outbox import OutboxEvent
from app.common.errors.exceptions import AppError
from app.common.storage.s3 import get_public_asset_url, get_tree_analysis_image_url
from app.modules.tree_analyses.models import IdempotencyRecord, TreeAnalysis, TreeScan
from app.modules.trees.models import (
    Tree,
    TreeEvent,
    TreeEventType,
    TreeImage,
    TreeImageKind,
    TreeLocation,
    TreeStatus,
)
from app.modules.trees.repository import TreeRepository
from app.modules.uploads.models import UploadedAsset


class TreeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TreeRepository(db)

    def idempotency_replay(
        self, owner_id: uuid.UUID, route: str, key: str, request_hash: str
    ) -> dict | None:
        row = (
            self.db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.principal_id == owner_id,
                IdempotencyRecord.method == "POST",
                IdempotencyRecord.route == route,
                IdempotencyRecord.key == key,
            )
            .with_for_update()
            .first()
        )
        if not row:
            return None
        if row.request_hash != request_hash:
            raise AppError(
                "idempotency_conflict",
                "Idempotency-Key was already used with a different request.",
                409,
            )
        if row.state == "completed" and row.response_body:
            return row.response_body
        raise AppError("request_in_progress", "The matching request is still processing.", 409)

    def idempotency_begin(
        self, owner_id: uuid.UUID, route: str, key: str, request_hash: str
    ) -> IdempotencyRecord:
        row = IdempotencyRecord(
            principal_id=owner_id,
            method="POST",
            route=route,
            key=key,
            request_hash=request_hash,
            state="received",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(row)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            replay = self.idempotency_replay(owner_id, route, key, request_hash)
            if replay is not None:
                raise AppError(
                    "request_in_progress",
                    "The matching request completed concurrently; retry to replay it.",
                    409,
                ) from exc
            raise
        return row

    def idempotency_complete(
        self, row: IdempotencyRecord, resource_id: uuid.UUID, payload: dict
    ) -> None:
        # JSONB does not accept Python datetime/UUID objects. The normal FastAPI
        # response path encodes them automatically, but durable replay storage
        # must cross that serialization boundary explicitly before committing.
        replay_payload = jsonable_encoder(payload)
        row.state = "completed"
        row.response_status = 201
        row.response_body = replay_payload
        row.resource_type = "tree"
        row.resource_id = resource_id
        self.db.commit()

    def _get_asset_for_owner(self, asset_id: str, owner_id: uuid.UUID) -> UploadedAsset:
        try:
            parsed = uuid.UUID(asset_id)
        except Exception as exc:
            raise AppError(
                "invalid_asset_id", "Image value must be uploaded asset id", 422
            ) from exc
        row = self.db.query(UploadedAsset).filter(UploadedAsset.id == parsed).first()
        if not row:
            raise AppError("asset_not_found", "Uploaded asset not found", 404)
        if row.owner_user_id != owner_id:
            raise AppError("asset_forbidden", "Uploaded asset does not belong to user", 403)
        return row

    def register_tree(
        self,
        owner_id: uuid.UUID,
        name: str,
        captured_at: datetime,
        lat: float,
        lng: float,
        accuracy_meters: float,
        image_asset_ids: dict[str, str],
    ) -> Tree:
        tree = Tree(
            owner_user_id=owner_id,
            name=name,
            captured_at=captured_at.astimezone(timezone.utc),
            status=TreeStatus.PENDING,
            ai_status="queued",
            is_public=True,
        )
        self.repo.create_tree(tree)

        for kind in [TreeImageKind.FRONT, TreeImageKind.TRUNK, TreeImageKind.LEAVES]:
            asset = self._get_asset_for_owner(image_asset_ids[kind.value], owner_id)
            asset.attached_at = datetime.now(timezone.utc)
            asset.expires_at = None
            asset.status = "attached"
            self.repo.create_image(
                TreeImage(tree_id=tree.id, uploaded_asset_id=asset.id, kind=kind)
            )

        point = WKTElement(f"POINT({lng} {lat})", srid=4326)
        self.repo.create_location(
            TreeLocation(
                tree_id=tree.id, location=point, accuracy_meters=accuracy_meters, source="mobile"
            )
        )
        self.repo.create_event(
            TreeEvent(
                tree_id=tree.id,
                actor_user_id=owner_id,
                event_type=TreeEventType.REGISTERED,
                details_json=json.dumps({"accuracy_meters": accuracy_meters}),
                created_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()
        self.db.refresh(tree)
        from app.common.tasks import analyze_tree_images

        analyze_tree_images.delay(str(tree.id))
        return tree

    def patch_tree(self, tree_id: uuid.UUID, actor_id: uuid.UUID, payload: dict) -> Tree:
        tree = self.repo.get_tree(tree_id)
        if not tree:
            raise AppError("not_found", "Tree not found", 404)
        if tree.owner_user_id != actor_id:
            raise AppError("forbidden", "Not tree owner", 403)
        nickname = payload.get("nickname", payload.get("name"))
        if nickname is not None:
            tree.name = nickname
        if "notes" in payload:
            tree.notes = payload["notes"]
        if "visibility" in payload:
            tree.is_public = payload["visibility"] == "public"
        species = payload.get("confirmed_species")
        if species:
            candidate_id = species.get("candidate_id") or species.get("id")
            candidate = None
            if candidate_id:
                if not tree.analysis_id:
                    raise AppError(
                        "invalid_species_candidate",
                        "This tree has no analysis candidates.",
                        422,
                    )
                candidate = self.repo.get_candidate(uuid.UUID(candidate_id), tree.analysis_id)
                if candidate is None:
                    raise AppError(
                        "invalid_species_candidate",
                        "Candidate does not belong to this tree's analysis.",
                        422,
                    )
            if candidate:
                tree.confirmed_species = candidate.scientific_name
                tree.confirmed_common_name = candidate.common_name
                tree.selected_candidate_id = candidate.id
                tree.manual_scientific_name = None
                tree.identification_source = "user_confirmed_ai"
            else:
                tree.confirmed_species = species["scientific_name"]
                tree.confirmed_common_name = species.get("common_name")
                tree.selected_candidate_id = None
                tree.manual_scientific_name = species["scientific_name"]
                tree.identification_source = "user_corrected"
        event_payload = {
            key: value
            for key, value in payload.items()
            if key != "name" or "nickname" not in payload
        }
        self.repo.create_event(
            TreeEvent(
                tree_id=tree.id,
                actor_user_id=actor_id,
                event_type=TreeEventType.UPDATED,
                details_json=json.dumps(event_payload),
                created_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()
        self.db.refresh(tree)
        return tree

    def verify_tree(self, tree_id: uuid.UUID, actor_id: uuid.UUID, note: str | None) -> Tree:
        tree = self.repo.get_tree(tree_id)
        if not tree:
            raise AppError("not_found", "Tree not found", 404)
        previous_status = tree.status.value
        tree.status = TreeStatus.VERIFIED
        self.repo.create_event(
            TreeEvent(
                tree_id=tree.id,
                actor_user_id=actor_id,
                event_type=TreeEventType.VERIFIED,
                details_json=json.dumps(
                    {
                        "note": note,
                        "reviewer_id": str(actor_id),
                        "previous_state": previous_status,
                        "new_state": TreeStatus.VERIFIED.value,
                        "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                created_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()
        self.db.refresh(tree)
        return tree

    def create_from_analysis(
        self,
        owner_id: uuid.UUID,
        analysis_id: uuid.UUID,
        selected_candidate_id: uuid.UUID | None,
        manual_scientific_name: str | None,
        location_evidence: dict,
        duplicate_check_status: str,
        nickname: str | None,
        notes: str | None,
        visibility: str,
        confirmed_common_name: str | None = None,
    ) -> Tree:
        analysis = self._completed_analysis(analysis_id, owner_id)
        from app.common.config import get_settings

        if getattr(analysis, "created_at", datetime.now(timezone.utc)) < datetime.now(
            timezone.utc
        ) - timedelta(hours=get_settings().analysis_ttl_hours):
            raise AppError("analysis_not_found", "Tree analysis has expired.", 404)
        if self.repo.get_scan_by_analysis(analysis.id):
            raise AppError("INVALID_STATE", "Analysis is already attached to a tree.", 409)
        original = analysis.location_evidence or {}
        lat = float(location_evidence["latitude"])
        lng = float(location_evidence["longitude"])
        original_lat = float(original.get("latitude", lat))
        original_lng = float(original.get("longitude", lng))
        d_lat = math.radians(lat - original_lat)
        d_lng = math.radians(lng - original_lng)
        haversine = (
            math.sin(d_lat / 2) ** 2
            + math.cos(math.radians(original_lat))
            * math.cos(math.radians(lat))
            * math.sin(d_lng / 2) ** 2
        )
        distance_meters = (
            6_371_000 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(max(0.0, 1 - haversine)))
        )
        allowed_drift = max(
            10.0,
            float(original.get("horizontal_accuracy_meters", 0))
            + float(location_evidence["horizontal_accuracy_meters"]),
        )
        if distance_meters > allowed_drift:
            raise AppError(
                "invalid_location_evidence",
                "Tree location materially differs from the analysis location.",
                422,
            )
        candidate = None
        if selected_candidate_id:
            candidate = self.repo.get_candidate(selected_candidate_id, analysis.id)
            if not candidate:
                raise AppError(
                    "validation_error", "Selected candidate does not belong to this analysis.", 422
                )
        candidate_species = candidate.scientific_name if candidate else None
        confirmed_species = manual_scientific_name or candidate_species
        common_name = candidate.common_name if candidate else confirmed_common_name
        identification_source = (
            "user_confirmed_ai"
            if candidate
            else "user_corrected"
            if manual_scientific_name
            else "unknown"
        )
        health = (analysis.normalized_result or {}).get("health") or {}
        display_name = nickname or confirmed_species or "Unnamed tree"
        captured_at = datetime.fromisoformat(
            str(location_evidence["captured_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        tree = Tree(
            owner_user_id=owner_id,
            name=display_name,
            captured_at=captured_at,
            status=TreeStatus.PENDING,
            ai_status="completed",
            ai_model_version=(analysis.provider_metadata or {}).get("model_version"),
            ai_summary_json=json.dumps(analysis.normalized_result or {}),
            ai_analyzed_at=analysis.analyzed_at,
            confirmed_species=confirmed_species,
            confirmed_common_name=common_name,
            candidate_species=candidate_species,
            analysis_id=analysis.id,
            selected_candidate_id=selected_candidate_id,
            manual_scientific_name=manual_scientific_name,
            identification_source=identification_source,
            duplicate_check_status=duplicate_check_status,
            notes=notes,
            latest_health_status=health.get("status"),
            is_public=visibility == "public",
        )
        self.repo.create_tree(tree)
        self.repo.create_location(
            TreeLocation(
                tree_id=tree.id,
                location=WKTElement(f"POINT({lng} {lat})", srid=4326),
                accuracy_meters=float(location_evidence["horizontal_accuracy_meters"]),
                source="analysis",
                accepted_sample_count=location_evidence["accepted_sample_count"],
                rejected_sample_count=location_evidence["rejected_sample_count"],
                capture_duration_ms=location_evidence["capture_duration_ms"],
                best_sample_accuracy_meters=location_evidence["best_sample_accuracy_meters"],
                evidence_captured_at=datetime.fromisoformat(
                    str(location_evidence["captured_at"]).replace("Z", "+00:00")
                ),
                quality=location_evidence["quality"],
            )
        )
        self.repo.create_scan(
            self._scan_from_analysis(tree.id, analysis, lat, lng, captured_at=captured_at)
        )
        self.repo.create_event(
            TreeEvent(
                tree_id=tree.id,
                actor_user_id=owner_id,
                event_type=TreeEventType.REGISTERED,
                details_json=json.dumps(
                    {"source": "tree_analysis", "analysis_id": str(analysis.id)}
                ),
                created_at=datetime.now(timezone.utc),
            )
        )
        self.db.add(
            OutboxEvent(
                aggregate_type="tree",
                aggregate_id=tree.id,
                event_type="tree.registered",
                payload={"tree_id": str(tree.id), "owner_id": str(owner_id)},
                available_at=datetime.now(timezone.utc),
            )
        )
        # The API commits the tree and durable replay response atomically.
        self.db.flush()
        self.db.refresh(tree)
        return tree

    def attach_scan(
        self,
        tree_id: uuid.UUID,
        owner_id: uuid.UUID,
        analysis_id: uuid.UUID,
        captured_at: datetime | None,
        notes: str | None,
    ) -> TreeScan:
        tree = self.repo.get_tree(tree_id)
        if not tree:
            raise AppError("TREE_NOT_FOUND", "Tree not found.", 404)
        if tree.owner_user_id != owner_id:
            raise AppError("FORBIDDEN", "Not tree owner.", 403)
        analysis = self._completed_analysis(analysis_id, owner_id)
        if self.repo.get_scan_by_analysis(analysis.id):
            raise AppError("INVALID_STATE", "Analysis is already attached to a tree.", 409)
        lat = analysis.latitude
        lng = analysis.longitude
        if lat is None or lng is None:
            lat, lng = self._read_lat_lng(tree.id)
        scan = self._scan_from_analysis(tree.id, analysis, lat, lng, captured_at, notes)
        self.repo.create_scan(scan)
        result = analysis.normalized_result or {}
        health = result.get("health") or {}
        tree.latest_health_status = health.get("status")
        tree.ai_status = "completed"
        tree.ai_summary_json = json.dumps(result)
        tree.ai_analyzed_at = analysis.analyzed_at
        self.db.commit()
        self.db.refresh(scan)
        return scan

    def _completed_analysis(self, analysis_id: uuid.UUID, owner_id: uuid.UUID) -> TreeAnalysis:
        analysis = self.repo.get_analysis(analysis_id, owner_id)
        if not analysis:
            raise AppError("ANALYSIS_NOT_FOUND", "Tree analysis not found.", 404)
        if analysis.status != "completed" or not analysis.normalized_result:
            raise AppError("ANALYSIS_NOT_COMPLETED", "Tree analysis is not completed.", 409)
        return analysis

    @staticmethod
    def _scan_from_analysis(
        tree_id: uuid.UUID,
        analysis: TreeAnalysis,
        latitude: float,
        longitude: float,
        captured_at: datetime | None = None,
        notes: str | None = None,
    ) -> TreeScan:
        result = analysis.normalized_result or {}
        analyzed_at = analysis.analyzed_at or datetime.now(timezone.utc)
        effective_captured_at = captured_at or analyzed_at
        if effective_captured_at.tzinfo is None:
            raise AppError("INVALID_TIMESTAMP", "captured_at must include a timezone.", 422)
        return TreeScan(
            tree_id=tree_id,
            analysis_id=analysis.id,
            captured_at=effective_captured_at.astimezone(timezone.utc),
            analyzed_at=analyzed_at,
            latitude=latitude,
            longitude=longitude,
            health_summary=result.get("health") or {"status": "not_available"},
            provider_name=getattr(
                analysis,
                "provider_name",
                result.get("provider", "kindwise_plant_id"),
            ),
            warnings=[],
            notes=notes,
        )

    @staticmethod
    def scan_to_payload(scan: TreeScan) -> dict:
        health = scan.health_summary or {"status": "not_available"}
        return {
            "id": str(scan.id),
            "scanned_at": scan.analyzed_at,
            "summary": scan.notes or "Follow-up visual scan",
            "image_url": None,
            "health": health,
            # Preserve the legacy mobile contract while retaining the real provider in the DB.
            "provider": "kindwise_plant_id",
            "capabilities": {
                "identification": "available",
                "health": (
                    "not_available" if health.get("status") == "not_available" else "available"
                ),
            },
            "attribution": {
                "provider": "Kindwise Plant.id",
                "provider_id": "kindwise_plant_id",
            },
            "uncertainty": {
                "confidence_scale": "0_to_1",
                "user_confirmation_required": True,
            },
            "warnings": scan.warnings,
        }

    def tree_to_payload(self, tree: Tree) -> dict:
        location_row = self.repo.get_location(tree.id)
        images = self.repo.get_images(tree.id)
        image_map: dict[str, str] = {}
        for img in images:
            asset = (
                self.db.query(UploadedAsset)
                .filter(UploadedAsset.id == img.uploaded_asset_id)
                .first()
            )
            if asset:
                image_map[img.kind.value] = get_public_asset_url(asset.id)

        lat, lng = self._read_lat_lng(tree.id)
        if location_row is None:
            lat, lng = 0.0, 0.0

        ai_summary = None
        if tree.ai_summary_json:
            try:
                ai_summary = json.loads(tree.ai_summary_json)
            except json.JSONDecodeError:
                ai_summary = {"status": tree.ai_status, "reason": "invalid_summary_payload"}

        recent_scans = self.repo.list_scans(tree.id, None, 5)

        primary_image_url = next(iter(image_map.values()), None)
        photos = [{"type": key, "url": value} for key, value in image_map.items()]
        if tree.analysis_id:
            analysis_images = self.repo.get_analysis_images(tree.analysis_id)
            photos = [
                {"type": image.organ, "url": get_tree_analysis_image_url(image.id)}
                for image in analysis_images
            ]
            primary_image_url = photos[0]["url"] if photos else None

        location = {
            "latitude": lat,
            "longitude": lng,
            "horizontal_accuracy_meters": location_row.accuracy_meters if location_row else 0,
            "accepted_sample_count": location_row.accepted_sample_count if location_row else None,
            "rejected_sample_count": location_row.rejected_sample_count if location_row else None,
            "capture_duration_ms": location_row.capture_duration_ms if location_row else None,
            "best_sample_accuracy_meters": location_row.best_sample_accuracy_meters
            if location_row
            else None,
            "captured_at": location_row.evidence_captured_at if location_row else tree.captured_at,
            "quality": location_row.quality if location_row else "poor",
        }
        selected = self._selected_candidate(tree)
        identification: dict[str, Any] = {
            "common_name": selected.common_name if selected else tree.confirmed_common_name,
            "scientific_name": tree.confirmed_species or tree.candidate_species,
            "ai_confidence": selected.confidence if selected else None,
            "ai_provider": "kindwise_plant_id" if tree.analysis_id else None,
            "source": tree.identification_source,
            "description": selected.description if selected else None,
        }
        location["accuracy_meters"] = location["horizontal_accuracy_meters"]
        result: dict[str, Any] = {
            "id": str(tree.id),
            "nickname": tree.name,
            "owner_id": str(tree.owner_user_id),
            "registered_at": tree.created_at,
            "last_scanned_at": recent_scans[0].analyzed_at if recent_scans else None,
            "primary_image_url": primary_image_url,
            "photos": photos,
            "location": location,
            "identification": identification,
            "notes": tree.notes,
            "visibility": "public" if tree.is_public else "private",
            "health": (ai_summary or {}).get("health") if ai_summary else None,
        }
        scientific_name = identification["scientific_name"]
        common_name = identification["common_name"]
        result.update(
            {
                "confirmed_species": (
                    {"scientific_name": scientific_name, "common_name": common_name}
                    if scientific_name
                    else None
                ),
                "latest_health": result["health"]
                or (
                    {"status": tree.latest_health_status}
                    if tree.latest_health_status
                    else {"status": "not_available"}
                ),
                "notes": tree.notes or "",
                "created_at": tree.created_at,
                "updated_at": tree.updated_at,
            }
        )
        return result

    def _selected_candidate(self, tree: Tree):
        if not tree.selected_candidate_id or not tree.analysis_id:
            return None
        return self.repo.get_candidate(tree.selected_candidate_id, tree.analysis_id)

    def tree_to_summary(self, tree: Tree) -> dict:
        detail = self.tree_to_payload(tree)
        identification = dict(detail["identification"])
        identification.pop("description", None)
        location = detail["location"]
        return {
            "id": detail["id"],
            "nickname": detail["nickname"],
            "primary_image_url": detail["primary_image_url"],
            "registered_at": detail["registered_at"],
            "last_scanned_at": detail["last_scanned_at"],
            "location": {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "horizontal_accuracy_meters": location["horizontal_accuracy_meters"],
                "accuracy_meters": location["accuracy_meters"],
                "quality": location["quality"],
            },
            "identification": identification,
            "health": detail["health"],
            "confirmed_species": detail["confirmed_species"],
            "latest_health": detail["latest_health"],
            "notes": detail["notes"],
            "created_at": detail["created_at"],
            "updated_at": detail["updated_at"],
        }

    @staticmethod
    def settings_public_media_base() -> str:
        from app.common.config import get_settings

        settings = get_settings()
        return f"{settings.s3_public_base_url.rstrip('/')}/{settings.s3_bucket}"

    @staticmethod
    def ensure_readable(tree: Tree | None, viewer_id: uuid.UUID) -> Tree:
        if not tree:
            raise AppError("TREE_NOT_FOUND", "Tree not found.", 404)
        if tree.owner_user_id != viewer_id and not tree.is_public:
            raise AppError("FORBIDDEN", "This tree profile is private.", 403)
        return tree

    def _read_lat_lng(self, tree_id: uuid.UUID) -> tuple[float, float]:
        row = self.db.execute(
            text(
                """
            SELECT ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
            FROM tree_locations WHERE tree_id=:tree_id
            """
            ),
            {"tree_id": tree_id},
        ).first()
        if not row:
            return 0.0, 0.0
        return float(row.lat), float(row.lng)
