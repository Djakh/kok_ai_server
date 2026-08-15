from fastapi import status

from app.modules.auth.dependencies import get_auth_service


class FakeAuthService:
    def register(self, payload):  # noqa: ANN001
        from app.modules.auth.schemas import TokenPairResponse

        return TokenPairResponse(access_token="a", refresh_token="r")

    login = register
    refresh = register

    def logout(self, refresh_token: str) -> None:
        assert refresh_token



def test_auth_register(client):
    client.app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "u@example.com", "username": "user1", "password": "Passw0rd11"},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["success"] is True
