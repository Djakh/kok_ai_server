import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit

import app.common.storage.s3 as storage_module
import app.modules.uploads.media_router as media_router_module
from app.common.db.session import get_db
from app.modules.uploads.schemas import UploadedAssetResponse
from app.modules.users.schemas import UserPublic


class FakeBody:
    def __init__(self, content: bytes):
        self.content = content
        self.closed = False

    def iter_chunks(self, chunk_size: int = 1024):
        del chunk_size
        yield self.content

    def close(self):
        self.closed = True


def test_public_asset_url_uses_api_not_private_storage(monkeypatch) -> None:
    asset_id = uuid.uuid4()
    monkeypatch.setattr(
        storage_module,
        "settings",
        SimpleNamespace(
            public_api_base_url="https://api.example.test/",
            api_prefix="/api/v1",
        ),
    )

    assert storage_module.get_public_asset_url(asset_id) == (
        f"https://api.example.test/api/v1/media/{asset_id}"
    )


def test_public_media_streams_private_object(client, monkeypatch) -> None:
    asset_id = uuid.uuid4()
    body = FakeBody(b"image-data")
    asset = SimpleNamespace(
        id=asset_id,
        storage_key="uploads/user/display.jpg",
        content_type="image/jpeg",
    )

    client.app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(media_router_module, "_published_asset", lambda db, value: asset)
    monkeypatch.setattr(
        media_router_module,
        "get_s3_client",
        lambda: SimpleNamespace(
            get_object=lambda **kwargs: {
                "Body": body,
                "ContentLength": len(body.content),
                "ETag": '"etag"',
            }
        ),
    )

    response = client.get(f"/api/v1/media/{asset_id}")

    assert response.status_code == 200
    assert response.content == b"image-data"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert body.closed is True


def test_analysis_image_uses_a_signed_api_url(client, monkeypatch) -> None:
    image_id = uuid.uuid4()
    body = FakeBody(b"private-image")
    settings = SimpleNamespace(
        public_api_base_url="https://api.example.test",
        api_prefix="/api/v1",
        jwt_access_secret="test-signing-secret",
    )
    monkeypatch.setattr(storage_module, "settings", settings)
    monkeypatch.setattr(storage_module.time, "time", lambda: 1_000)
    image = SimpleNamespace(
        id=image_id,
        object_key="tree-analyses/user/image.jpg",
        mime_type="image/jpeg",
    )
    client.app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(media_router_module, "_attached_analysis_image", lambda db, value: image)
    monkeypatch.setattr(
        media_router_module,
        "get_s3_client",
        lambda: SimpleNamespace(
            get_object=lambda **kwargs: {
                "Body": body,
                "ContentLength": len(body.content),
            }
        ),
    )

    signed_url = storage_module.get_tree_analysis_image_url(image_id)
    parsed = urlsplit(signed_url)
    response = client.get(f"{parsed.path}?{parsed.query}")

    assert response.status_code == 200
    assert response.content == b"private-image"
    assert response.headers["cache-control"] == "private, max-age=900"
    assert body.closed is True

    tampered = client.get(
        f"/api/v1/media/tree-analysis/{image_id}?expires=1900&signature=invalid"
    )
    assert tampered.status_code == 404

    expired = client.get(
        f"/api/v1/media/tree-analysis/{image_id}?expires=999&signature=invalid"
    )
    assert expired.status_code == 404


def test_serializers_replace_stale_database_urls(monkeypatch) -> None:
    monkeypatch.setattr(
        storage_module,
        "settings",
        SimpleNamespace(
            public_api_base_url="https://api.example.test",
            api_prefix="/api/v1",
        ),
    )
    asset_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    upload = UploadedAssetResponse.model_validate(
        {
            "id": asset_id,
            "url": "http://localhost:9000/bucket/old.jpg",
            "content_type": "image/jpeg",
            "file_name": "old.jpg",
            "file_size": 10,
            "width": 1,
            "height": 1,
            "purpose": "social_post",
            "status": "attached",
            "attached_at": now,
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    user = UserPublic.model_validate(
        {
            "id": uuid.uuid4(),
            "email": "person@example.com",
            "username": "person",
            "full_name": None,
            "role": "user",
            "bio": None,
            "avatar_url": "http://localhost:9000/bucket/avatar.jpg",
            "avatar_asset_id": asset_id,
            "created_at": now,
        }
    )

    expected = f"https://api.example.test/api/v1/media/{asset_id}"
    assert upload.url == expected
    assert user.avatar_url == expected
    assert "avatar_asset_id" not in user.model_dump(mode="json")
