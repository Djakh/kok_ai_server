import uuid

from fastapi import APIRouter, Depends

from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.users.dependencies import get_user_service
from app.modules.users.schemas import (
    AccountDeleteRequest,
    AvatarUpdateRequest,
    UserMe,
    UserPublic,
    UserUpdateRequest,
)
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def get_me(current: CurrentUser = Depends(get_current_user)):
    return success_response(UserMe.model_validate(current.user).model_dump(mode="json"))


@router.patch("/me")
def patch_me(
    payload: UserUpdateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    user = service.update_me(current.user.id, payload)
    return success_response(UserMe.model_validate(user).model_dump(mode="json"))


@router.patch("/me/avatar")
def patch_avatar(
    payload: AvatarUpdateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    user = service.update_avatar(current.user.id, payload.upload_id)
    return success_response(UserMe.model_validate(user).model_dump(mode="json"))


@router.delete("/me/avatar")
def delete_avatar(
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    user = service.remove_avatar(current.user.id)
    return success_response(UserMe.model_validate(user).model_dump(mode="json"))


@router.get("/me/export")
def export_me(
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return success_response(service.export_personal_data(current.user.id))


@router.post("/me/deactivate")
def deactivate_me(
    payload: AccountDeleteRequest,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    service.deactivate(current.user.id, payload.password)
    return success_response({"deactivated": True, "sessions_revoked": True})


@router.delete("/me")
def delete_me(
    payload: AccountDeleteRequest,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    service.delete_account(current.user.id, payload.password)
    return success_response({"deleted": True, "sessions_revoked": True})


@router.get("/{user_id}")
def get_user(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    del current
    user = service.repo.get_by_id(user_id)
    if not user:
        from app.common.errors.exceptions import AppError

        raise AppError("not_found", "User not found", 404)
    return success_response(UserPublic.model_validate(user).model_dump(mode="json"))


@router.get("/{user_id}/followers")
def followers(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    del current
    items = [
        UserPublic.model_validate(x).model_dump(mode="json")
        for x in service.repo.list_followers(user_id)
    ]
    return success_response({"items": items, "next_cursor": None})


@router.get("/{user_id}/following")
def following(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    del current
    items = [
        UserPublic.model_validate(x).model_dump(mode="json")
        for x in service.repo.list_following(user_id)
    ]
    return success_response({"items": items, "next_cursor": None})


@router.post("/{user_id}/follow")
def follow(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    service.follow(current.user.id, user_id)
    return success_response({"following": True})


@router.delete("/{user_id}/follow")
def unfollow(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    service.unfollow(current.user.id, user_id)
    return success_response({"following": False})
