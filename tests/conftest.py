import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.common.security.dependencies import CurrentUser, get_current_user
from app.main import app


@pytest.fixture
def client():
    user = SimpleNamespace(
        id=uuid.uuid4(),
        email="test@example.com",
        username="tester",
        full_name="Tester",
        role="user",
        bio=None,
        avatar_url=None,
        created_at=datetime.now(timezone.utc),
        is_active=True,
    )

    def _current_user_override():
        return CurrentUser(user=user)

    app.dependency_overrides[get_current_user] = _current_user_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
