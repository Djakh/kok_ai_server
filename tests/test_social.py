import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import app.modules.social.router as social_router_module
from app.modules.social.dependencies import get_social_service


class FakePost:
    def __init__(self):
        self.id = uuid.uuid4()
        self.created_at = datetime.now(timezone.utc)


class FakeRepo:
    def __init__(self):
        self.comments_store: dict[str, list[SimpleNamespace]] = {}

    def list_posts(self, cursor, limit, user_id, near):  # noqa: ANN001
        return [FakePost()]

    def list_comments(self, post_id):  # noqa: ANN001
        return self.comments_store.get(str(post_id), [])


class FakeSocialService:
    def __init__(self):
        self.repo = FakeRepo()

    def post_payload(self, post):  # noqa: ANN001
        return {
            "id": str(post.id),
            "author_id": str(uuid.uuid4()),
            "content": "hello",
            "image_url": None,
            "location": {"latitude": None, "longitude": None},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def create_post(self, user_id, content, created_at, upload_id, latitude, longitude):  # noqa: ANN001
        return FakePost()

    def add_comment(self, post_id, user_id, content):  # noqa: ANN001
        row = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=user_id,
            post_id=post_id,
            content=content,
            created_at=datetime.now(timezone.utc),
        )
        self.repo.comments_store.setdefault(str(post_id), []).append(row)
        return row



def test_social_posts_list(client):
    client.app.dependency_overrides[get_social_service] = lambda: FakeSocialService()
    resp = client.get("/api/v1/social/posts?limit=1")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_social_multipart_create(client, monkeypatch):
    class FakeUploadService:
        def __init__(self, db):  # noqa: ANN001
            self.db = db

        def upload_single(self, file, owner_id):  # noqa: ANN001
            return type("Upload", (), {"id": uuid.uuid4()})()

    client.app.dependency_overrides[get_social_service] = lambda: FakeSocialService()
    monkeypatch.setattr(social_router_module, "UploadService", FakeUploadService)
    data = {"content": "hello", "created_at": "2026-03-27T13:32:00+00:00"}
    files = {"image": ("post.jpg", b"abc", "image/jpeg")}
    resp = client.post("/api/v1/social/posts", data=data, files=files)
    assert resp.status_code == 201
    assert resp.json()["success"] is True


def test_social_comment_create_then_list(client):
    fake_service = FakeSocialService()
    client.app.dependency_overrides[get_social_service] = lambda: fake_service
    post_id = str(uuid.uuid4())
    create_resp = client.post(
        f"/api/v1/social/posts/{post_id}/comments",
        json={"content": "Nice tree"},
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["data"]["author_id"]

    list_resp = client.get(f"/api/v1/social/posts/{post_id}/comments")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["data"]) == 1
    assert list_resp.json()["data"][0]["author_id"] == create_resp.json()["data"]["author_id"]
