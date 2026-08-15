from app.modules.profile.dependencies import get_profile_service
from app.modules.users.dependencies import get_user_service


class FakeProfileService:
    def stats(self, user_id):  # noqa: ANN001
        return {"followers_count": 1, "following_count": 1, "posts_count": 1, "trees_count": 1}

    class achievements:
        @staticmethod
        def list_for_user(user_id):  # noqa: ANN001
            return []

    class social:
        @staticmethod
        def list_posts(cursor, limit, user_id, near):  # noqa: ANN001
            return []

        @staticmethod
        def liked_posts(user_id):  # noqa: ANN001
            return []


class FakeUserService:
    class Settings:
        language_code = "en"
        privacy_profile_public = True
        notifications_enabled = True

    def get_or_create_settings(self, user_id):  # noqa: ANN001
        return self.Settings()

    update_settings = get_or_create_settings
    update_localization = get_or_create_settings



def test_profile_stats(client):
    client.app.dependency_overrides[get_profile_service] = lambda: FakeProfileService()
    resp = client.get("/api/v1/profile/me/stats")
    assert resp.status_code == 200
    assert resp.json()["data"]["followers_count"] == 1



def test_profile_settings(client):
    client.app.dependency_overrides[get_user_service] = lambda: FakeUserService()
    resp = client.get("/api/v1/profile/me/settings")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
