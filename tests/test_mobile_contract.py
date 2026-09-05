import io
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from app.modules.auth.dependencies import get_auth_service
from app.modules.mobile_support.dependencies import get_mobile_support_service
from app.modules.notifications.dependencies import get_notification_service
from app.modules.profile.dependencies import get_profile_service
from app.modules.social.schemas import (
    CommentCreateRequest,
    SocialCreateByUploadRequest,
    SocialPatchRequest,
)
from app.modules.tree_analyses.dependencies import get_tree_analysis_service
from app.modules.trees.dependencies import get_tree_service
from app.modules.trees.schemas import TreeCreateFromAnalysisRequest, TreePatchRequest
from app.modules.trees.service import TreeService
from app.modules.uploads.dependencies import get_upload_service


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), color=(20, 120, 40)).save(output, format="JPEG")
    return output.getvalue()


def test_mobile_analysis_alias_contract(client) -> None:
    analysis_id = uuid.uuid4()

    class FakeAnalysisService:
        async def analyze(self, owner_id, images, photo_types, evidence, key):  # noqa: ANN001
            assert owner_id
            assert len(images) == 3
            assert photo_types == ["whole_tree", "bark", "leaf"]
            assert evidence["latitude"] == 41.3
            assert key == "mobile-alias-1"
            return (
                SimpleNamespace(
                    normalized_result={
                        "id": str(analysis_id),
                        "provider": "kindwise_plant_id",
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                        "candidates": [],
                        "health": None,
                    }
                ),
                False,
            )

    client.app.dependency_overrides[get_tree_analysis_service] = lambda: FakeAnalysisService()
    response = client.post(
        "/api/v1/tree-analyses",
        files=[
            ("images", ("whole.jpg", _jpeg(), "image/jpeg")),
            ("images", ("bark.jpg", _jpeg(), "image/jpeg")),
            ("images", ("leaf.jpg", _jpeg(), "image/jpeg")),
        ],
        data={
            "organs": ["auto", "bark", "leaf"],
            "latitude": "41.3",
            "longitude": "69.2",
            "accuracy_meters": "4.5",
        },
        headers={"Idempotency-Key": "mobile-alias-1"},
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["species_candidates"] == []
    assert data["health"]["status"] == "not_available"
    assert data["capabilities"]["health"] == "not_available"
    assert data["attribution"]["provider_id"] == "kindwise_plant_id"


def test_confirmed_species_mobile_request_is_canonicalized() -> None:
    candidate_id = uuid.uuid4()
    payload = TreeCreateFromAnalysisRequest.model_validate(
        {
            "analysis_id": str(uuid.uuid4()),
            "confirmed_species": {
                "id": str(candidate_id),
                "scientific_name": "Platanus orientalis",
                "common_name": "Oriental plane",
            },
            "latitude": 41.3,
            "longitude": 69.2,
            "accuracy_meters": 4.5,
        }
    )
    assert payload.selected_candidate_id == candidate_id
    assert payload.location_evidence is not None
    assert payload.location_evidence.accepted_sample_count == 3


def test_confirmed_species_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TreeCreateFromAnalysisRequest.model_validate(
            {
                "analysis_id": str(uuid.uuid4()),
                "confirmed_species": {
                    "scientific_name": "Platanus orientalis",
                    "unexpected": "must not be ignored",
                },
                "latitude": 41.3,
                "longitude": 69.2,
            }
        )


def test_tree_patch_contract_is_owner_editable_but_not_location_or_status() -> None:
    payload = TreePatchRequest.model_validate(
        {
            "nickname": "North gate plane",
            "notes": None,
            "visibility": "public",
            "confirmed_species": {
                "scientific_name": "Platanus orientalis",
                "common_name": "Oriental plane",
            },
        }
    )
    assert payload.nickname == "North gate plane"
    assert payload.notes is None
    with pytest.raises(ValidationError):
        TreePatchRequest.model_validate({"location": {"latitude": 1, "longitude": 2}})
    with pytest.raises(ValidationError):
        TreePatchRequest.model_validate({"status": "verified"})


def test_social_json_contract_and_image_removal_are_strict() -> None:
    created = SocialCreateByUploadRequest.model_validate(
        {
            "content": "My tree",
            "location": {"latitude": None, "longitude": None},
            "created_at": datetime.now(timezone.utc),
        }
    )
    assert created.location.latitude is None
    assert SocialPatchRequest.model_validate({"remove_image": True}).remove_image is True
    assert CommentCreateRequest.model_validate({"content": "Nice tree"}).content == "Nice tree"
    with pytest.raises(ValidationError):
        SocialPatchRequest.model_validate({"remove_image": False})
    with pytest.raises(ValidationError):
        SocialCreateByUploadRequest.model_validate(
            {
                "content": "My tree",
                "location": {"latitude": 41.3, "longitude": None},
                "created_at": datetime.now(timezone.utc),
            }
        )


def test_tree_payload_contains_stable_mobile_core() -> None:
    now = datetime.now(timezone.utc)
    tree = SimpleNamespace(
        id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        name="School plane",
        created_at=now,
        updated_at=now,
        captured_at=now,
        analysis_id=None,
        selected_candidate_id=None,
        confirmed_species="Platanus orientalis",
        confirmed_common_name="Oriental plane",
        candidate_species=None,
        identification_source="user_corrected",
        notes=None,
        is_public=True,
        latest_health_status=None,
        ai_summary_json=None,
    )

    class FakeRepo:
        @staticmethod
        def get_location(tree_id):  # noqa: ANN001
            return SimpleNamespace(
                accuracy_meters=4.2,
                accepted_sample_count=3,
                rejected_sample_count=0,
                capture_duration_ms=1,
                best_sample_accuracy_meters=4.2,
                evidence_captured_at=now,
                quality="acceptable",
            )

        @staticmethod
        def get_images(tree_id):  # noqa: ANN001
            return []

        @staticmethod
        def list_scans(tree_id, cursor, limit):  # noqa: ANN001
            return []

    service = TreeService.__new__(TreeService)
    service.repo = FakeRepo()
    service.db = SimpleNamespace()
    service._read_lat_lng = lambda tree_id: (41.3, 69.2)  # type: ignore[method-assign]
    data = service.tree_to_payload(tree)
    for field in (
        "id",
        "nickname",
        "confirmed_species",
        "location",
        "latest_health",
        "primary_image_url",
        "notes",
        "created_at",
        "updated_at",
    ):
        assert field in data
    assert data["location"]["accuracy_meters"] == 4.2
    assert data["confirmed_species"]["common_name"] == "Oriental plane"
    assert data["latest_health"]["status"] == "not_available"


def test_mobile_route_aliases_and_version_contract(client) -> None:
    class FakeProfile:
        def stats(self, user_id):  # noqa: ANN001
            return {
                "tree_count": 1,
                "post_count": 2,
                "follower_count": 3,
                "following_count": 4,
            }

    class FakeUpload:
        @staticmethod
        def upload_single(file, owner_id, purpose="general"):  # noqa: ANN001
            now = datetime.now(timezone.utc)
            return SimpleNamespace(
                id=uuid.uuid4(),
                url="https://cdn.example.test/file.jpg",
                content_type="image/jpeg",
                file_name="file.jpg",
                file_size=10,
                width=10,
                height=10,
                purpose=purpose,
                status="available",
                attached_at=None,
                expires_at=now,
                created_at=now,
                updated_at=now,
            )

    client.app.dependency_overrides[get_profile_service] = lambda: FakeProfile()
    client.app.dependency_overrides[get_upload_service] = lambda: FakeUpload()
    assert client.get("/api/v1/profile/stats").status_code == 200
    assert client.get("/api/v1/languages").json()["data"]["items"]
    upload = client.post(
        "/api/v1/uploads",
        files={"file": ("a.jpg", b"abc", "image/jpeg")},
        data={"purpose": "avatar"},
    )
    assert upload.status_code == 201
    assert upload.json()["data"]["purpose"] == "avatar"
    version = client.get("/api/v1/version?platform=ios&current_version=1.0.0").json()["data"]
    assert "minimum_supported_version" in version
    assert "latest_version" in version
    assert "force_upgrade" in version
    assert "maintenance_status" in version
    missing_version = client.get("/api/v1/version").json()["data"]
    assert missing_version["force_upgrade"] is False
    assert missing_version["platform"] is None
    assert client.get("/api/v1/version?current_version=1.2").status_code == 422


def test_notification_read_all_post_alias(client) -> None:
    class FakeNotificationService:
        @staticmethod
        def mark_all_read(user_id):  # noqa: ANN001
            return 2

    client.app.dependency_overrides[get_notification_service] = lambda: FakeNotificationService()
    response = client.post("/api/v1/notifications/read-all")
    assert response.status_code == 200
    assert response.json()["data"]["updated"] == 2


def test_account_recovery_routes(client) -> None:
    class FakeAuth:
        @staticmethod
        def request_password_recovery(email):  # noqa: ANN001
            return {"accepted": True, "expires_in": 600}

        @staticmethod
        def verify_password_recovery(email, code):  # noqa: ANN001
            return {"verified": True, "reset_token": "x" * 32}

        @staticmethod
        def reset_password(token, password):  # noqa: ANN001
            assert token and password

    client.app.dependency_overrides[get_auth_service] = lambda: FakeAuth()
    requested = client.post(
        "/api/v1/auth/password-recovery/request", json={"email": "u@example.com"}
    )
    assert requested.status_code == 200
    verified = client.post(
        "/api/v1/auth/password-recovery/verify",
        json={"email": "u@example.com", "code": "123456"},
    )
    assert verified.json()["data"]["verified"] is True
    reset = client.post(
        "/api/v1/auth/password-recovery/reset",
        json={"reset_token": "x" * 32, "new_password": "NewPass123"},
    )
    assert reset.json()["data"]["password_reset"] is True


def test_device_report_block_and_tree_issue_routes(client) -> None:
    now = datetime.now(timezone.utc)

    class FakeSupport:
        @staticmethod
        def upsert_device(user_id, payload):  # noqa: ANN001
            return SimpleNamespace(
                installation_id=payload.installation_id,
                platform=payload.platform,
                locale=payload.locale,
                app_version=payload.app_version,
                last_seen_at=now,
                enabled=True,
                push_token=payload.push_token,
                created_at=now,
                updated_at=now,
            )

        @staticmethod
        def device_payload(row):  # noqa: ANN001
            return {"installation_id": row.installation_id, "token_last_four": row.push_token[-4:]}

        @staticmethod
        def create_report(user_id, payload):  # noqa: ANN001
            return SimpleNamespace(
                id=uuid.uuid4(),
                target_type=payload.target_type,
                target_id=payload.target_id,
                reason=payload.reason,
                status="submitted",
                created_at=now,
                updated_at=now,
            )

        @staticmethod
        def report_payload(row):  # noqa: ANN001
            return {"id": str(row.id), "status": row.status}

        @staticmethod
        def block_user(user_id, target_id):  # noqa: ANN001
            return SimpleNamespace()

        @staticmethod
        def create_tree_issue(user_id, tree_id, payload):  # noqa: ANN001
            return SimpleNamespace(
                id=uuid.uuid4(),
                tree_id=tree_id,
                category=payload.category,
                notes=payload.notes,
                upload_ids=[],
                latitude=None,
                longitude=None,
                status="submitted",
                created_at=now,
                updated_at=now,
            )

        @staticmethod
        def issue_payload(row):  # noqa: ANN001
            return {"id": str(row.id), "status": row.status}

    client.app.dependency_overrides[get_mobile_support_service] = lambda: FakeSupport()
    device = client.post(
        "/api/v1/devices",
        json={
            "installation_id": "installation-123",
            "push_token": "a" * 32,
            "platform": "ios",
            "locale": "en",
            "app_version": "1.0.0",
        },
    )
    assert device.status_code == 201
    assert device.json()["data"]["token_last_four"] == "aaaa"
    target_id = uuid.uuid4()
    report = client.post(
        "/api/v1/reports",
        json={"target_type": "post", "target_id": str(target_id), "reason": "spam"},
    )
    assert report.status_code == 201
    assert client.post(f"/api/v1/users/{target_id}/block").status_code == 200
    issue = client.post(
        f"/api/v1/trees/{uuid.uuid4()}/issues",
        json={"category": "damage", "notes": "Broken branch"},
    )
    assert issue.status_code == 201


def test_openapi_contains_mobile_product_contract(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/devices",
        "/api/v1/reports",
        "/api/v1/users/{user_id}/block",
        "/api/v1/users/me/blocked",
        "/api/v1/trees/{tree_id}/issues",
        "/api/v1/trees/issues/mine",
        "/api/v1/auth/password-recovery/request",
        "/api/v1/auth/change-password",
        "/api/v1/auth/sessions",
        "/api/v1/users/me/avatar",
        "/api/v1/users/me/export",
    }
    assert expected <= paths.keys()


def test_map_rejects_excessive_viewport(client) -> None:
    client.app.dependency_overrides[get_tree_service] = lambda: SimpleNamespace()
    response = client.get("/api/v1/trees/map?bbox=0,0,10,10")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "map_area_too_large"
