import uuid

from fastapi import APIRouter, Depends

from app.common.rate_limit.dependencies import AuthRateLimit, auth_identity_rate_limit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordRecoveryRequest,
    PasswordRecoveryVerifyRequest,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    VerificationConfirmRequest,
    VerificationRequest,
)
from app.modules.auth.service import AuthService
from app.modules.users.schemas import UserMe

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
    return success_response(UserMe.model_validate(current.user).model_dump(mode="json"))


@router.post("/password-recovery/request", dependencies=[AuthRateLimit])
def request_password_recovery(
    payload: PasswordRecoveryRequest,
    service: AuthService = Depends(get_auth_service),
):
    auth_identity_rate_limit(payload.email)
    return success_response(service.request_password_recovery(payload.email))


@router.post("/password-recovery/verify", dependencies=[AuthRateLimit])
def verify_password_recovery(
    payload: PasswordRecoveryVerifyRequest,
    service: AuthService = Depends(get_auth_service),
):
    auth_identity_rate_limit(payload.email)
    return success_response(service.verify_password_recovery(payload.email, payload.code))


@router.post("/password-recovery/reset", dependencies=[AuthRateLimit])
def reset_password(
    payload: PasswordResetRequest,
    service: AuthService = Depends(get_auth_service),
):
    service.reset_password(payload.reset_token, payload.new_password)
    return success_response({"password_reset": True})


@router.post("/verification/request")
@router.post("/verification/resend")
def request_verification(
    payload: VerificationRequest,
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return success_response(service.request_verification(current.user, payload))


@router.post("/verification/verify")
def confirm_verification(
    payload: VerificationConfirmRequest,
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return success_response(
        service.confirm_verification(current.user, payload.channel, payload.code)
    )


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    service.change_password(current.user, payload.current_password, payload.new_password)
    return success_response({"password_changed": True, "sessions_revoked": True})


@router.get("/sessions")
def list_sessions(
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return success_response(
        {"items": service.sessions(current.user.id, current.session_id), "next_cursor": None}
    )


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    service.revoke_session(current.user.id, session_id)
    return success_response({"revoked": True, "session_id": str(session_id)})


@router.delete("/sessions")
def revoke_all_sessions(
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    service.revoke_all_sessions(current.user.id)
    return success_response({"revoked": True, "all_sessions": True})
