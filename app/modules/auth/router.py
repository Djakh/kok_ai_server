from fastapi import APIRouter, Depends

from app.common.rate_limit.dependencies import AuthRateLimit, auth_identity_rate_limit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.schemas import LoginRequest, RefreshRequest, RegisterRequest
from app.modules.auth.service import AuthService
from app.modules.users.schemas import UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", dependencies=[AuthRateLimit])
def register(payload: RegisterRequest, service: AuthService = Depends(get_auth_service)):
    auth_identity_rate_limit(payload.email)
    tokens = service.register(payload)
    return success_response(tokens.model_dump())


@router.post("/login", dependencies=[AuthRateLimit])
def login(payload: LoginRequest, service: AuthService = Depends(get_auth_service)):
    auth_identity_rate_limit(payload.email)
    tokens = service.login(payload)
    return success_response(tokens.model_dump())


@router.post("/refresh", dependencies=[AuthRateLimit])
def refresh(payload: RefreshRequest, service: AuthService = Depends(get_auth_service)):
    tokens = service.refresh(payload)
    return success_response(tokens.model_dump())


@router.post("/logout")
def logout(
    payload: RefreshRequest,
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    del current
    service.logout(payload.refresh_token)
    return success_response({"logged_out": True})


@router.get("/me")
def me(current: CurrentUser = Depends(get_current_user)):
    return success_response(UserPublic.model_validate(current.user).model_dump(mode="json"))
