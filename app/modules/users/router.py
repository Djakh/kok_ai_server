import uuid

from fastapi import APIRouter, Depends

from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.users.dependencies import get_user_service
from app.modules.users.schemas import UserPublic, UserUpdateRequest
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def get_me(current: CurrentUser = Depends(get_current_user)):
    return success_response(UserPublic.model_validate(current.user).model_dump(mode="json"))


@router.patch("/me")
def patch_me(
    payload: UserUpdateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    user = service.update_me(current.user.id, payload)
    return success_response(UserPublic.model_validate(user).model_dump(mode="json"))


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
    items = [UserPublic.model_validate(x).model_dump(mode="json") for x in service.repo.list_followers(user_id)]
    return success_response(items)


@router.get("/{user_id}/following")
def following(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    del current
    items = [UserPublic.model_validate(x).model_dump(mode="json") for x in service.repo.list_following(user_id)]
    return success_response(items)


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
