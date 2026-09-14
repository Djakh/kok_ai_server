import uuid
from datetime import datetime, timezone

import pytest

import app.modules.trees.router as trees_router_module
from app.common.errors.exceptions import AppError
from app.common.pagination.cursor import decode_cursor
from app.modules.trees.dependencies import get_tree_service
from app.modules.trees.repository import TreeRepository


class FakeTree:
    def __init__(self):
        self.id = uuid.uuid4()
        self.created_at = datetime.now(timezone.utc)


class FakeTreeRepo:
    def list_trees(self, cursor, limit, status, owner_id, q, sort, viewer_id, *args):  # noqa: ANN001
        return [FakeTree()]


class FakeTreeService:
    def __init__(self):
        self.repo = FakeTreeRepo()

    def tree_to_payload(self, tree):  # noqa: ANN001
        return {
            "id": str(tree.id),
            "nickname": "Tree",
            "owner_id": str(uuid.uuid4()),
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "location": {"latitude": 1.0, "longitude": 2.0},
        }

    tree_to_summary = tree_to_payload

    def register_tree(
        self, owner_id, name, captured_at, lat, lng, accuracy_meters, image_asset_ids  # noqa: ANN001
    ):
        return FakeTree()


class RecordingQuery:
    def __init__(self):
        self.filters = []

    def filter(self, *criteria):  # noqa: ANN002
        self.filters.extend(criteria)
        return self

    def join(self, *args):  # noqa: ANN002
        return self

    def order_by(self, *args):  # noqa: ANN002
        return self

    def limit(self, value):  # noqa: ANN001
        return self

    def all(self):
        return []



def test_trees_list(client):
    client.app.dependency_overrides[get_tree_service] = lambda: FakeTreeService()
    resp = client.get("/api/v1/trees?limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]["items"]) == 1


def test_tree_list_defaults_to_current_owner_and_map_has_no_owner_scope() -> None:
    viewer_id = uuid.uuid4()

    list_query = RecordingQuery()
    list_repo = TreeRepository.__new__(TreeRepository)
    list_repo.db = type("DB", (), {"query": lambda self, model: list_query})()
    list_repo.list_trees(None, 20, None, None, None, "newest", viewer_id)
    list_filters = " ".join(str(value) for value in list_query.filters)
    assert "trees.owner_user_id" in list_filters
    assert "trees.is_public" not in list_filters

    map_query = RecordingQuery()
    map_repo = TreeRepository.__new__(TreeRepository)
    map_repo.db = type("DB", (), {"query": lambda self, model: map_query})()
    map_repo.map_bbox(69.0, 41.0, 69.5, 41.5, None, viewer_id)
    map_filters = " ".join(str(value) for value in map_query.filters)
    assert "trees.owner_user_id" not in map_filters
    assert "trees.is_public" not in map_filters
    assert "trees.deleted_at" in map_filters


def test_trees_multipart_register(client, monkeypatch):
    class FakeUploadService:
        def __init__(self, db):  # noqa: ANN001
            self.db = db

        def upload_single(self, file, owner_id):  # noqa: ANN001
            return type("Upload", (), {"id": uuid.uuid4()})()

    monkeypatch.setattr(trees_router_module, "UploadService", FakeUploadService)
    client.app.dependency_overrides[get_tree_service] = lambda: FakeTreeService()
    data = {
        "name": "Oak",
        "latitude": "41.2995",
        "longitude": "69.2401",
        "accuracy_meters": "2.5",
        "captured_at": "2026-03-27T13:32:00+00:00",
    }
    files = {
        "front": ("front.jpg", b"abc", "image/jpeg"),
        "trunk": ("trunk.jpg", b"abc", "image/jpeg"),
        "leaves": ("leaves.jpg", b"abc", "image/jpeg"),
    }
    resp = client.post("/api/v1/trees/register", data=data, files=files)
    assert resp.status_code == 201
    assert resp.json()["success"] is True


def test_private_tree_is_owner_only() -> None:
    owner_id = uuid.uuid4()
    private_tree = type(
        "PrivateTree", (), {"owner_user_id": owner_id, "is_public": False}
    )()
    from app.modules.trees.service import TreeService

    assert TreeService.ensure_readable(private_tree, owner_id) is private_tree
    with pytest.raises(AppError) as exc_info:
        TreeService.ensure_readable(private_tree, uuid.uuid4())
    assert exc_info.value.code == "FORBIDDEN"


def test_invalid_cursor_returns_safe_error() -> None:
    with pytest.raises(AppError) as exc_info:
        decode_cursor("not-a-cursor")
    assert exc_info.value.code == "INVALID_CURSOR"
    assert exc_info.value.status_code == 422
