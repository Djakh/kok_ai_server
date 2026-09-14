from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.common.middleware.request_size as request_size_module
from app.common.middleware.request_size import RequestSizeLimitMiddleware


def _client(monkeypatch, maximum: int, overhead: int) -> TestClient:
    monkeypatch.setattr(
        request_size_module,
        "get_settings",
        lambda: SimpleNamespace(
            ai_max_request_bytes=maximum,
            request_multipart_overhead_bytes=overhead,
        ),
    )
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware)

    @app.post("/upload")
    def upload():
        return {"accepted": True}

    return TestClient(app)


def test_request_at_configured_limit_reaches_application(monkeypatch) -> None:
    with _client(monkeypatch, maximum=40_000_000, overhead=2_000_000) as client:
        response = client.post(
            "/upload",
            content=b"x",
            headers={"Content-Length": "42000000"},
        )

    assert response.status_code == 200


def test_oversized_request_returns_json_413(monkeypatch) -> None:
    with _client(monkeypatch, maximum=40_000_000, overhead=2_000_000) as client:
        response = client.post(
            "/upload",
            content=b"x",
            headers={"Content-Length": "42000001"},
        )

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"] == {
        "code": "upload_too_large",
        "message": "The request exceeds the configured upload limit.",
        "request_id": None,
        "details": {"max_request_bytes": 42_000_000},
    }
