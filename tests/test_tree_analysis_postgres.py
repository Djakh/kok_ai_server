import io
import itertools
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.common.config import Settings
from app.common.db.session import engine
from app.common.security.dependencies import CurrentUser, get_current_user
from app.main import app
from app.modules.tree_analyses.dependencies import get_tree_analysis_service
from app.modules.tree_analyses.models import TreeAnalysis
from app.modules.tree_analyses.provider import ProviderResult, SpeciesCandidate
from app.modules.tree_analyses.service import TreeAnalysisService
from app.modules.users.models import User, UserRole


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 800), color=(42, 120, 55)).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _location_evidence() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "latitude": 41.3111,
        "longitude": 69.2797,
        "horizontal_accuracy_meters": 12.0,
        "accepted_sample_count": 3,
        "rejected_sample_count": 0,
        "capture_duration_ms": 1500,
        "best_sample_accuracy_meters": 9.0,
        "captured_at": (now - timedelta(seconds=10)).isoformat(),
        "quality": "acceptable",
    }


class _FakeProvider:
    name = "test-provider"

    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, images, organs, context=None):  # noqa: ANN001
        self.calls += 1
        assert context and isinstance(context["custom_id"], int)
        return ProviderResult(
            species_candidates=[
                SpeciesCandidate(
                    scientific_name="Platanus orientalis",
                    common_names=["Oriental plane"],
                    confidence=0.91,
                )
            ],
            provider_metadata={"model_version": "postgres-regression"},
        )

    async def retrieve(self, custom_id):  # noqa: ANN001
        return None


@pytest.mark.asyncio
async def test_postgres_fresh_analysis_and_idempotency_contract() -> None:
    try:
        connection = engine.connect()
    except OperationalError:
        pytest.skip("PostgreSQL is not reachable from this test process")
    if connection.dialect.name != "postgresql":
        connection.close()
        pytest.skip("This regression requires PostgreSQL")

    outer = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        db_column = next(
            column
            for column in inspect(connection).get_columns("tree_analyses")
            if column["name"] == "numeric_provider_custom_id"
        )
        assert db_column["nullable"] is False
        assert "tree_analysis_provider_custom_id_seq" in str(db_column["default"])

        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=f"analysis-{user_id}@example.test",
            username=f"analysis_{user_id.hex[:20]}",
            password_hash="not-used-in-test",
            role=UserRole.USER,
        )
        db.add(user)
        db.flush()

        settings = Settings(_env_file=None)
        image_bytes = _jpeg_bytes()
        provider = _FakeProvider()
        keys = itertools.count()

        def storage_writer(content, owner_id, content_type, extension):  # noqa: ANN001
            return f"test/tree-analysis/{user_id}/{next(keys)}.{extension}"

        service = TreeAnalysisService(db, provider, settings, storage_writer)
        evidence = _location_evidence()
        idempotency_key = f"postgres-{uuid.uuid4()}"

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(user=user)
        app.dependency_overrides[get_tree_analysis_service] = lambda: service

        async def post_analysis(organs: list[str]) -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://postgres-regression.test"
            ) as client:
                return await client.post(
                    "/api/v1/tree-analyses",
                    files=[
                        ("images", ("whole.jpg", image_bytes, "image/jpeg")),
                        ("images", ("bark.jpg", image_bytes, "image/jpeg")),
                        ("images", ("leaf.jpg", image_bytes, "image/jpeg")),
                    ],
                    data={
                        "organs": organs,
                        "location_evidence": json.dumps(evidence),
                    },
                    headers={"Idempotency-Key": idempotency_key},
                )

        first = await post_analysis(["auto", "bark", "leaf"])
        assert first.status_code == 201, first.text
        assert first.json()["meta"] is None
        created_id = uuid.UUID(first.json()["data"]["id"])
        created = db.query(TreeAnalysis).filter(TreeAnalysis.id == created_id).one()
        assert created.numeric_provider_custom_id is not None
        first_custom_id = created.numeric_provider_custom_id
        assert provider.calls == 1

        replay = await post_analysis(["auto", "bark", "leaf"])
        assert replay.status_code == 200, replay.text
        assert replay.json()["meta"] == {"idempotency_replayed": True}
        assert uuid.UUID(replay.json()["data"]["id"]) == created.id
        assert provider.calls == 1

        conflict = await post_analysis(["auto", "flower_or_fruit", "leaf"])
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        assert provider.calls == 1

        stored = db.query(TreeAnalysis).filter(TreeAnalysis.id == created.id).one()
        assert stored.numeric_provider_custom_id == first_custom_id
        assert (
            db.query(TreeAnalysis)
            .filter(TreeAnalysis.numeric_provider_custom_id == first_custom_id)
            .count()
            == 1
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_tree_analysis_service, None)
        db.close()
        outer.rollback()
        connection.close()
