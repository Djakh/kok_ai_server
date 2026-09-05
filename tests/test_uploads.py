import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.modules.uploads.dependencies import get_upload_service


class FakeUploadService:
    def upload_single(self, file, owner_id, purpose="general"):  # noqa: ANN001
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=uuid.uuid4(),
            url="http://localhost/file.jpg",
            content_type="image/jpeg",
            file_name="file.jpg",
            file_size=100,
            width=100,
            height=100,
            purpose=purpose,
            status="available",
            attached_at=None,
            expires_at=now,
            created_at=now,
            updated_at=now,
        )

    def get_owned(self, upload_id, owner_id):  # noqa: ANN001
        return self.upload_single(None, owner_id)


def test_upload_single(client):
    client.app.dependency_overrides[get_upload_service] = lambda: FakeUploadService()
    files = {"file": ("a.jpg", b"abc", "image/jpeg")}
    resp = client.post("/api/v1/uploads/images", files=files)
    assert resp.status_code == 201
    assert resp.json()["success"] is True
