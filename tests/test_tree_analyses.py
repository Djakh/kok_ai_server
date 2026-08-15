import asyncio
import io
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import UploadFile
from PIL import Image

from app.common.config import Settings
from app.common.errors.exceptions import AppError
from app.common.observability import analysis_concurrency_slot
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.tree_analyses.dependencies import get_tree_analysis_service
from app.modules.tree_analyses.images import (
    _prepare_one,
    prepare_images,
    validate_photo_types,
)
from app.modules.tree_analyses.kindwise import KindwisePlantIdClient
from app.modules.tree_analyses.provider import (
    ProviderError,
    ProviderImage,
    clamp_confidence,
)
from app.modules.tree_analyses.service import TreeAnalysisService
from app.modules.trees.dependencies import get_tree_service
from app.modules.trees.service import TreeService


def jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), color=(20, 120, 40)).save(output, format="JPEG")
    return output.getvalue()


def location_evidence() -> dict:
    return {
        "latitude": 41.3,
        "longitude": 69.2,
        "horizontal_accuracy_meters": 5.8,
        "accepted_sample_count": 8,
        "rejected_sample_count": 2,
        "capture_duration_ms": 12000,
        "best_sample_accuracy_meters": 4.2,
        "captured_at": "2026-08-15T05:00:12Z",
        "quality": "acceptable",
    }


def test_image_signature_and_decode_are_validated() -> None:
    settings = Settings(_env_file=None)
    prepared = _prepare_one(jpeg_bytes(), "tree.jpg", settings)
    assert prepared.content_type == "image/jpeg"
    assert len(prepared.checksum) == 64

    with pytest.raises(AppError) as exc_info:
        _prepare_one(b"not-an-image", "tree.jpg", settings)
    assert exc_info.value.code == "INVALID_IMAGE"
    assert exc_info.value.status_code == 415

    with pytest.raises(AppError) as decode_error:
        _prepare_one(b"\xff\xd8\xffcorrupt", "tree.jpg", settings)
    assert decode_error.value.code in {"INVALID_IMAGE", "IMAGE_DECODE_FAILED"}


@pytest.mark.asyncio
async def test_oversized_image_is_rejected() -> None:
    upload = UploadFile(file=io.BytesIO(jpeg_bytes()), filename="tree.jpg")
    with pytest.raises(AppError) as exc_info:
        await prepare_images(
            [upload], Settings(_env_file=None, ai_max_image_bytes=10, ai_max_request_bytes=20)
        )
    assert exc_info.value.code == "UPLOAD_TOO_LARGE"
    assert exc_info.value.status_code == 413


def test_photo_type_contract() -> None:
    assert validate_photo_types(["whole_tree", "leaf"], 2) == ["whole_tree", "leaf"]
    with pytest.raises(AppError):
        validate_photo_types(["leaf", "leaf"], 2)


def test_kindwise_normalization_preserves_probability_and_nullable_fields() -> None:
    result = KindwisePlantIdClient.normalize(
        {
            "access_token": "never-return-this",
            "model_version": "v-test",
            "result": {
                "is_plant": {"binary": True, "probability": 0.9},
                "classification": {
                    "suggestions": [
                        {
                            "id": "taxon-1",
                            "name": "Platanus orientalis",
                            "probability": 0.42,
                            "details": {
                                "common_names": ["Oriental plane"],
                                "taxonomy": {"genus": "Platanus", "family": "Platanaceae"},
                            },
                        }
                    ]
                },
            },
        }
    )
    assert result.species_candidates[0].confidence == 0.42
    assert result.species_candidates[0].description is None
    assert result.is_plant is True


@pytest.mark.asyncio
async def test_kindwise_exact_server_request_and_empty_candidates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/identification"
        assert request.headers["Api-Key"] == "server-secret"
        assert request.url.params["details"].startswith("common_names,description,taxonomy")
        body = await request.aread()
        assert b'custom_id' in body and b'12345' in body
        assert b'suggestion_filter' in body and b'tree' in body
        assert b'classification_level' in body and b'species' in body
        assert body.count(b'filename="') == 2
        return httpx.Response(
            201,
            json={
                "access_token": "provider-private",
                "model_version": "test",
                "result": {
                    "is_plant": {"binary": True, "probability": 0.61},
                    "classification": {"suggestions": []},
                },
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://plant.id/api/v3"
    )
    provider = KindwisePlantIdClient(
        Settings(_env_file=None, kindwise_api_key="server-secret"), client
    )
    result = await provider.analyze(
        [
            ProviderImage(jpeg_bytes(), "image/jpeg", "whole.jpg"),
            ProviderImage(jpeg_bytes(), "image/jpeg", "leaf.jpg"),
        ],
        ["whole_tree", "leaf"],
        {
            "custom_id": 12345,
            "location_evidence": {
                "latitude": 41.3,
                "longitude": 69.2,
                "captured_at": "2026-08-15T05:00:12Z",
            },
        },
    )
    await client.aclose()
    assert result.species_candidates == []
    assert result.is_plant is True
    assert "provider-private" not in repr(result.species_candidates)


def test_kindwise_no_plant_and_health_mapping() -> None:
    no_plant = KindwisePlantIdClient.normalize(
        {
            "result": {
                "is_plant": {"binary": False, "probability": 0.08},
                "classification": {"suggestions": []},
            }
        }
    )
    assert no_plant.is_plant is False

    unhealthy = KindwisePlantIdClient.normalize(
        {
            "result": {
                "is_plant": {"binary": True, "probability": 0.99},
                "is_healthy": {"binary": False, "probability": 0.2},
                "classification": {"suggestions": []},
                "disease": {
                    "suggestions": [
                        {"name": "generic", "probability": 0.9, "redundant": True},
                        {"name": "Powdery mildew", "probability": 0.64},
                    ]
                },
            }
        }
    )
    assert unhealthy.health == {
        "status": "possible_issue",
        "confidence": 0.64,
        "summary": "Powdery mildew",
    }


def test_kindwise_localized_details_fall_back_to_english() -> None:
    result = KindwisePlantIdClient.normalize(
        {
            "result": {
                "is_plant": {"binary": True, "probability": 1},
                "classification": {
                    "suggestions": [
                        {
                            "id": "1",
                            "name": "Platanus orientalis",
                            "probability": 0.7,
                            "details": {
                                "common_names": {"uz": None, "en": ["Oriental plane"]},
                                "description": {
                                    "uz": None,
                                    "en": {
                                        "value": "English fallback",
                                        "citation": "Fixture source",
                                    },
                                },
                            },
                        }
                    ]
                },
            }
        },
        "uz",
    )
    candidate = result.species_candidates[0]
    assert candidate.common_names == ["Oriental plane"]
    assert candidate.description == "English fallback"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "headers", "code", "http_status"),
    [
        (401, {}, "ai_provider_misconfigured", 503),
        (429, {}, "ai_quota_exceeded", 429),
        (429, {"Retry-After": "12"}, "ai_rate_limited", 429),
        (503, {}, "ai_provider_unavailable", 502),
        (400, {}, "ai_provider_rejected_input", 422),
    ],
)
async def test_kindwise_safe_error_mapping(status, headers, code, http_status) -> None:  # noqa: ANN001
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, headers=headers)),
        base_url="https://plant.id/api/v3",
    )
    provider = KindwisePlantIdClient(
        Settings(_env_file=None, kindwise_api_key="server-secret"), client
    )
    with pytest.raises(ProviderError) as exc_info:
        await provider.analyze(
            [ProviderImage(jpeg_bytes(), "image/jpeg", "whole.jpg")],
            ["whole_tree"],
            {
                "custom_id": 1,
                "location_evidence": {
                    "latitude": 41.3,
                    "longitude": 69.2,
                    "captured_at": "2026-08-15T05:00:12Z",
                },
            },
        )
    await client.aclose()
    assert exc_info.value.code == code
    assert exc_info.value.status_code == http_status


def test_confidence_is_clamped() -> None:
    assert clamp_confidence(1.4) == 1.0
    assert clamp_confidence(-0.2) == 0.0
    assert clamp_confidence("bad") == 0.0


@pytest.mark.asyncio
async def test_global_analysis_concurrency_is_bounded() -> None:
    active = 0
    maximum = 0

    async def worker() -> None:
        nonlocal active, maximum
        async with analysis_concurrency_slot():
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(8)))
    assert maximum <= Settings(_env_file=None).ai_max_concurrent_analyses


@pytest.mark.asyncio
async def test_analysis_idempotency_replays_and_conflicts() -> None:
    owner_id = uuid.uuid4()
    existing = SimpleNamespace(
        status="completed",
        normalized_result={"status": "completed"},
        request_fingerprint="same",
    )

    class FakeRepo:
        def get_by_idempotency(self, requested_owner, key):  # noqa: ANN001
            assert requested_owner == owner_id
            assert key == "mobile-1"
            return existing

    service = TreeAnalysisService.__new__(TreeAnalysisService)
    service.repo = FakeRepo()
    class EmptyQuery:
        def filter(self, *args):  # noqa: ANN002
            return self

        def with_for_update(self):
            return self

        def first(self):
            return None

    service.db = SimpleNamespace(query=lambda model: EmptyQuery())
    service.provider = SimpleNamespace()
    service.settings = Settings(_env_file=None)
    image = _prepare_one(jpeg_bytes(), "tree.jpg", service.settings)

    from app.modules.tree_analyses.service import request_fingerprint

    evidence = {"latitude": 41.3, "longitude": 69.2}
    existing.request_fingerprint = request_fingerprint([image], ["whole_tree"], evidence)
    replayed, was_replayed = await service.analyze(
        owner_id, [image], ["whole_tree"], evidence, "mobile-1"
    )
    assert replayed is existing
    assert was_replayed is True

    with pytest.raises(AppError) as exc_info:
        await service.analyze(owner_id, [image], ["leaf"], evidence, "mobile-1")
    assert exc_info.value.code == "idempotency_conflict"


def test_completed_analysis_cannot_be_attached_twice() -> None:
    analysis = SimpleNamespace(
        id=uuid.uuid4(),
        status="completed",
        normalized_result={"speciesCandidates": [], "health": {}},
        latitude=41.3,
        longitude=69.2,
    )

    class FakeRepo:
        def get_analysis(self, analysis_id, owner_id):  # noqa: ANN001
            return analysis

        def get_scan_by_analysis(self, analysis_id):  # noqa: ANN001
            return SimpleNamespace(id=uuid.uuid4())

    service = TreeService.__new__(TreeService)
    service.repo = FakeRepo()
    with pytest.raises(AppError) as exc_info:
        service.create_from_analysis(
            uuid.uuid4(),
            analysis.id,
            None,
            None,
            location_evidence(),
            "noNearbyTrees",
            None,
            None,
            "private",
        )
    assert exc_info.value.code == "INVALID_STATE"
    assert exc_info.value.status_code == 409


def test_analysis_api_valid_multipart_and_provider_failure(client) -> None:
    analysis_id = uuid.uuid4()

    class FakeAnalysisService:
        async def analyze(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return (
                SimpleNamespace(
                    normalized_result={
                        "id": str(analysis_id),
                        "provider": "kindwise_plant_id",
                        "candidates": [],
                        "health": None,
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                False,
            )

    client.app.dependency_overrides[get_tree_analysis_service] = lambda: FakeAnalysisService()
    response = client.post(
        "/api/v1/tree-analyses",
        files=[
            ("photos", ("tree.jpg", jpeg_bytes(), "image/jpeg")),
            ("photos", ("leaf.jpg", jpeg_bytes(), "image/jpeg")),
        ],
        data={
            "photo_types": ["whole_tree", "leaf"],
            "location_evidence": json.dumps(location_evidence()),
        },
        headers={"Idempotency-Key": "analysis-1"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["provider"] == "kindwise_plant_id"

    bad = client.post(
        "/api/v1/tree-analyses",
        files=[
            ("photos", ("tree.jpg", b"fake", "image/jpeg")),
            ("photos", ("leaf.jpg", jpeg_bytes(), "image/jpeg")),
        ],
        data={"photo_types": ["whole_tree", "leaf"], "location_evidence": json.dumps(location_evidence())},
        headers={"Idempotency-Key": "analysis-bad"},
    )
    assert bad.status_code == 415
    assert bad.json()["error"]["code"] == "invalid_image"
    assert bad.json()["error"]["request_id"]

    class FailingAnalysisService:
        async def analyze(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AppError("AI_PROVIDER_UNAVAILABLE", "Provider unavailable.", 503)

    client.app.dependency_overrides[get_tree_analysis_service] = lambda: FailingAnalysisService()
    failed = client.post(
        "/api/v1/tree-analyses",
        files=[
            ("photos", ("tree.jpg", jpeg_bytes(), "image/jpeg")),
            ("photos", ("leaf.jpg", jpeg_bytes(), "image/jpeg")),
        ],
        data={"photo_types": ["whole_tree", "leaf"], "location_evidence": json.dumps(location_evidence())},
        headers={"Idempotency-Key": "analysis-fail"},
    )
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "ai_provider_unavailable"


def test_tree_creation_from_completed_analysis_api(client) -> None:
    tree_id = uuid.uuid4()

    class FakeTreeService:
        def idempotency_replay(self, *args):  # noqa: ANN002
            return None

        def idempotency_begin(self, *args):  # noqa: ANN002
            return object()

        def idempotency_complete(self, *args):  # noqa: ANN002
            return None

        def create_from_analysis(self, *args):  # noqa: ANN002
            return SimpleNamespace(id=tree_id)

        def tree_to_payload(self, tree):  # noqa: ANN001
            return {"id": str(tree.id), "species": {"confirmed": "Platanus orientalis"}}

    client.app.dependency_overrides[get_tree_service] = lambda: FakeTreeService()
    response = client.post(
        "/api/v1/trees",
        json={
            "analysis_id": str(uuid.uuid4()),
            "manual_scientific_name": "Platanus orientalis",
            "location_evidence": location_evidence(),
            "duplicate_check_status": "noNearbyTrees",
            "visibility": "private",
        },
        headers={"Idempotency-Key": "tree-create-1"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["id"] == str(tree_id)


def test_rescan_and_paginated_history_api(client) -> None:
    owner_id = uuid.uuid4()
    tree_id = uuid.uuid4()
    analysis_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    scan = SimpleNamespace(
        id=uuid.uuid4(),
        tree_id=tree_id,
        analysis_id=analysis_id,
        captured_at=now,
        analyzed_at=now,
        latitude=41.3,
        longitude=69.2,
        health_summary={"status": "not_available"},
        provider_name="kindwise_plant_id",
        warnings=[],
        notes=None,
    )

    client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user=SimpleNamespace(id=owner_id)
    )

    class FakeRepo:
        def get_tree(self, requested_tree_id):  # noqa: ANN001
            assert requested_tree_id == tree_id
            return SimpleNamespace(id=tree_id, owner_user_id=owner_id)

        def list_scans(self, requested_tree_id, cursor, limit):  # noqa: ANN001
            assert requested_tree_id == tree_id
            assert limit == 1
            return [scan]

    class FakeTreeService:
        repo = FakeRepo()

        def _read_lat_lng(self, requested_tree_id):  # noqa: ANN001
            return 41.3, 69.2

        def attach_scan(self, *args):  # noqa: ANN002
            return scan

        @staticmethod
        def scan_to_payload(row):  # noqa: ANN001
            return {
                "id": str(row.id),
                "scanned_at": row.analyzed_at,
                "summary": "Follow-up visual scan",
                "image_url": None,
            }

    class FakeAnalysisService:
        async def analyze(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return SimpleNamespace(id=analysis_id), False

    client.app.dependency_overrides[get_tree_service] = lambda: FakeTreeService()
    client.app.dependency_overrides[get_tree_analysis_service] = lambda: FakeAnalysisService()

    created = client.post(
        f"/api/v1/trees/{tree_id}/scans",
        files=[
            ("photos", ("tree.jpg", jpeg_bytes(), "image/jpeg")),
            ("photos", ("leaf.jpg", jpeg_bytes(), "image/jpeg")),
        ],
        data={"photo_types": ["whole_tree", "leaf"], "run_analysis": "true"},
        headers={"Idempotency-Key": "scan-1"},
    )
    assert created.status_code == 201
    assert created.json()["data"]["id"] == str(scan.id)

    history = client.get(f"/api/v1/trees/{tree_id}/scans?limit=1")
    assert history.status_code == 200
    assert len(history.json()["data"]["items"]) == 1
