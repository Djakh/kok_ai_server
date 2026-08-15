from fastapi import APIRouter, Depends

from app.common.enums.constants import SUPPORTED_LANGUAGES
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.profile.dependencies import get_profile_service
from app.modules.profile.service import ProfileService
from app.modules.users.dependencies import get_user_service
from app.modules.users.schemas import (
    LocalizationUpdateRequest,
    UserSettingsResponse,
    UserSettingsUpdateRequest,
)
from app.modules.users.service import UserService

router = APIRouter(prefix="/profile", tags=["profile"])
localization_router = APIRouter(prefix="/localization", tags=["localization"])


@router.get("/me/stats")
def my_stats(
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    return success_response(service.stats(current.user.id))


@router.get("/me/achievements")
def my_achievements(
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    rows = service.achievements.list_for_user(current.user.id)
    return success_response(
        [{"id": str(x.id), "code": x.code, "title": x.title, "description": x.description} for x in rows]
    )


@router.get("/me/posts")
def my_posts(
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    rows = service.social.list_posts(None, 100, current.user.id, None)
    return success_response(
        [
            {
                "id": str(x.id),
                "content": x.content,
                "created_at": x.created_at,
            }
            for x in rows
        ]
    )


@router.get("/me/liked-posts")
def liked_posts(
    current: CurrentUser = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    rows = service.social.liked_posts(current.user.id)
    return success_response(
        [
            {
                "id": str(x.id),
                "content": x.content,
                "created_at": x.created_at,
            }
            for x in rows
        ]
    )


@router.get("/me/settings")
def settings_get(
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    row = service.get_or_create_settings(current.user.id)
    return success_response(UserSettingsResponse.model_validate(row).model_dump(mode="json"))


@router.patch("/me/settings")
def settings_patch(
    payload: UserSettingsUpdateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    row = service.update_settings(current.user.id, payload)
    return success_response(UserSettingsResponse.model_validate(row).model_dump(mode="json"))


@localization_router.get("/languages")
def languages():
    return success_response([{"code": x} for x in SUPPORTED_LANGUAGES])


@router.patch("/me/localization")
def localization_patch(
    payload: LocalizationUpdateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    row = service.update_localization(current.user.id, payload)
    return success_response(UserSettingsResponse.model_validate(row).model_dump(mode="json"))
