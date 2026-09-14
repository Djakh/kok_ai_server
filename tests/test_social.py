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
        self.last_list_args = None

    def list_posts(  # noqa: ANN001
        self, cursor, limit, user_id, near, following_only=False
    ):
        self.last_list_args = (cursor, limit, user_id, near, following_only)
        return [FakePost()]

    def count_posts(self, user_id):  # noqa: ANN001
        return 1

    def list_comments(self, post_id, cursor=None, limit=51):  # noqa: ANN001
        del cursor
        return self.comments_store.get(str(post_id), [])[:limit]

    def get_post(self, post_id):  # noqa: ANN001
        return FakePost()


class FakeSocialService:
    def __init__(self):
        self.repo = FakeRepo()
        self.create_args = None
        self.db = SimpleNamespace(
            query=lambda model: SimpleNamespace(
                filter=lambda *args: SimpleNamespace(
                    first=lambda: SimpleNamespace(
                        id=uuid.uuid4(),
                        username="author",
                        full_name="Author",
                        avatar_asset_id=None,
                    )
                )
            )
        )

    def post_payload(self, post):  # noqa: ANN001
        return {
            "id": str(post.id),
            "author_id": str(uuid.uuid4()),
            "content": "hello",
            "image_url": None,
            "image": None,
            "images": [],
            "image_width": None,
            "image_height": None,
            "image_aspect_ratio": None,
            "location": {"latitude": None, "longitude": None},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def create_post(self, user_id, content, created_at, upload_id, latitude, longitude):  # noqa: ANN001
        self.create_args = (user_id, content, created_at, upload_id, latitude, longitude)
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


def test_social_feed_scopes_and_author_timelines(client):
    fake_service = FakeSocialService()
    client.app.dependency_overrides[get_social_service] = lambda: fake_service

    following = client.get("/api/v1/social/feed?scope=following&limit=10")
    assert following.status_code == 200
    assert fake_service.repo.last_list_args[-1] is True

    mine = client.get("/api/v1/social/posts/me")
    assert mine.status_code == 200
    assert mine.json()["data"]["total_count"] == 1
    assert mine.json()["data"]["author"]["username"] == "tester"

    author_id = uuid.uuid4()
    authored = client.get(f"/api/v1/social/authors/{author_id}/posts")
    assert authored.status_code == 200
    assert fake_service.repo.last_list_args[2] == author_id
    assert authored.json()["data"]["author"]["username"] == "author"


def test_social_near_filter_validation(client):
    client.app.dependency_overrides[get_social_service] = lambda: FakeSocialService()

    response = client.get("/api/v1/social/posts?near=91,69,100")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_near"


def test_social_multipart_create(client, monkeypatch):
    class FakeUploadService:
        def __init__(self, db):  # noqa: ANN001
            self.db = db

        def upload_single(self, file, owner_id, purpose="general"):  # noqa: ANN001
            assert purpose == "social_post"
            return type("Upload", (), {"id": uuid.uuid4()})()

    client.app.dependency_overrides[get_social_service] = lambda: FakeSocialService()
    monkeypatch.setattr(social_router_module, "UploadService", FakeUploadService)
    data = {"content": "hello", "created_at": "2026-03-27T13:32:00+00:00"}
    files = {"image": ("post.jpg", b"abc", "image/jpeg")}
    resp = client.post("/api/v1/social/posts", data=data, files=files)
    assert resp.status_code == 201
    assert resp.json()["success"] is True


def test_social_json_create_with_upload_does_not_require_location(client, monkeypatch):
    fake_service = FakeSocialService()
    client.app.dependency_overrides[get_social_service] = lambda: fake_service
    monkeypatch.setattr(social_router_module, "get_replayed_response", lambda *args: None)
    monkeypatch.setattr(social_router_module, "save_response", lambda *args: None)
    upload_id = str(uuid.uuid4())

    response = client.post(
        "/api/v1/social/posts",
        json={
            "content": "fff",
            "upload_id": upload_id,
            "created_at": "2026-09-13T16:53:54.449409Z",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 201
    assert response.json()["success"] is True
    assert fake_service.create_args[3:] == (upload_id, None, None)


def test_social_json_validation_returns_422_instead_of_500(client):
    client.app.dependency_overrides[get_social_service] = lambda: FakeSocialService()

    response = client.post(
        "/api/v1/social/posts",
        json={"content": "fff", "created_at": "2026-09-13T16:53:54"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["field_errors"]


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
    assert len(list_resp.json()["data"]["items"]) == 1
    assert (
        list_resp.json()["data"]["items"][0]["author_id"] == create_resp.json()["data"]["author_id"]
    )
