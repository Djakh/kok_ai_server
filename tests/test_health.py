from fastapi.testclient import TestClient

from app.main import app


def test_root() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_liveness_only() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_endpoint_is_prometheus_text() -> None:
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_languages() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/localization/languages")

    assert response.status_code == 200
    assert response.json()["success"] is True
